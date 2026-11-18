"""Hermes CLI only: publish lifecycle, present request-bound human decisions."""
import os
import sys
import importlib.util
import gc
import threading
import time
import weakref
import math
import uuid
from types import SimpleNamespace

# Installed copies receive a machine-local path; source imports resolve the checkout.
from pathlib import Path
import json
_runtime = Path(__file__).with_name('runtime.json')
ROOT = str(Path(json.loads(_runtime.read_text())['repo_root']) if _runtime.exists()
           else Path(__file__).resolve().parents[2])
spec = importlib.util.spec_from_file_location('opendeck_cli_bridge', ROOT+'/tools/cli_agent_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
approval_dialog, publish = bridge.approval_dialog, bridge.publish


def ui_snapshot(cli):
    """Use the TUI's finally-protected busy flag, including cancelled turns."""
    agent = getattr(cli, 'agent', None)
    session = getattr(agent, 'session_id', None) or getattr(cli, 'session_id', None)
    if not session or not hasattr(cli, '_agent_running'):
        return None
    return str(session), bool(cli._agent_running)


def ui_throughput(cli):
    """Match Hermes CLIStatusBarMixin's rolling API throughput exactly."""
    agent = getattr(cli, 'agent', None)
    try:
        latency = list(getattr(agent, '_api_latency_history', []) or [])
        output = list(getattr(agent, '_api_output_history', []) or [])
        n = min(len(latency), len(output))
        if not n:
            return None
        seconds = sum(latency[-n:])
        value = sum(output[-n:])/seconds if seconds > 0 else None
        return value if value is not None and math.isfinite(value) else None
    except (TypeError, ValueError, RuntimeError):
        return None


def ui_context(cli):
    """Read the native compressor view, also mirrored by gateway-backed CLIs.

    Gateway API hooks run outside the interactive process. The CLI already
    receives last-request usage and the resolved window in session.usage; no
    second metadata lookup, guessed window, or conversation copy is needed.
    """
    compressor = getattr(getattr(cli, 'agent', None), 'context_compressor', None)
    used = getattr(compressor, 'last_prompt_tokens', None)
    limit = getattr(compressor, 'context_length', None)
    def valid(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return {
        'context_used': used if valid(used) and used >= 0 else None,
        'context_limit': limit if valid(limit) and limit > 0 else None,
    }


class QuestionMonitor:
    """Expose native clarification panels as expiring, request-bound controls."""
    def __init__(self):
        self.key = self.request = None

    def clear(self):
        if self.request:
            for folder in ('pending', 'decisions'):
                (bridge.CACHE/folder/(self.request+'.json')).unlink(missing_ok=True)
        self.key = self.request = None

    @staticmethod
    def signature(cli, state, app):
        return (id(state), state.get('active'), state.get('question'),
                state.get('selected'), tuple(sorted(state.get('selected_indices') or [])),
                bool(getattr(cli, '_clarify_freetext', False)), app.current_buffer.text)

    def tick(self, cli):
        state = getattr(cli, '_clarify_state', None)
        app = getattr(cli, '_app', None)
        if not state or not app or not getattr(app, 'loop', None):
            self.clear()
            return
        key = self.signature(cli, state, app)
        if key != self.key:
            self.clear()
            self.key, self.request = key, uuid.uuid4().hex
        request = self.request
        bridge.atomic(bridge.CACHE/'pending'/(request+'.json'), {
            'request': request, 'agent': 'hermes', 'kind': 'question',
            'pid': os.getpid(), 'expires': time.time()+3, 'extended': False,
            'allow_tool': False, 'title': 'Hermes question'})
        response = bridge.CACHE/'decisions'/(request+'.json')
        result = bridge.read(response)
        response.unlink(missing_ok=True)
        if result.get('request') != request or result.get('decision') not in ('approve', 'deny'):
            return
        self.clear()

        def apply():
            current = getattr(cli, '_clarify_state', None)
            if current is not state or self.signature(cli, current, app) != key:
                return
            if result['decision'] == 'deny':
                # Match Hermes' native question cancellation semantics.
                state['response_queue'].put('The user cancelled. Use your best judgement to proceed.')
                cli._clarify_teardown()
                app.invalidate()
            else:
                event = SimpleNamespace(app=app)
                if getattr(cli, '_clarify_freetext', False):
                    cli._tui_enter_clarify_freetext(event)
                else:
                    cli._tui_enter_clarify_choice(event)
        app.loop.call_soon_threadsafe(apply)


class ApprovalMonitor(QuestionMonitor):
    """Observe builtin permission panels, including transport fallback prompts."""
    @staticmethod
    def signature(cli, state, app):
        return (id(state), state.get('command'), state.get('description'),
                tuple(state.get('choices') or []), state.get('selected'),
                id(state.get('response_queue')), getattr(cli, '_approval_deadline', 0))

    def tick(self, cli):
        state = getattr(cli, '_approval_state', None)
        app = getattr(cli, '_app', None)
        deadline = getattr(cli, '_approval_deadline', 0)
        if (not state or not app or not getattr(app, 'loop', None)
                or deadline <= time.monotonic()
                or not {'once', 'deny'}.issubset(state.get('choices') or [])):
            self.clear()
            return
        key = self.signature(cli, state, app)
        if key != self.key:
            self.clear()
            self.key, self.request = key, uuid.uuid4().hex
        request = self.request
        bridge.atomic(bridge.CACHE/'pending'/(request+'.json'), {
            'request': request, 'agent': 'hermes', 'kind': 'native_approval',
            'pid': os.getpid(), 'expires': time.time()+min(3, deadline-time.monotonic()),
            'extended': False, 'allow_tool': False, 'title': 'Hermes permission'})
        response = bridge.CACHE/'decisions'/(request+'.json')
        result = bridge.read(response)
        response.unlink(missing_ok=True)
        if result.get('request') != request or result.get('decision') not in ('approve', 'deny'):
            return
        self.clear()

        def apply():
            current = getattr(cli, '_approval_state', None)
            if (current is not state or self.signature(cli, current, app) != key
                    or getattr(cli, '_approval_deadline', 0) <= time.monotonic()):
                return
            # Approve always means once, even if the UI highlights a wider grant.
            choice = 'once' if result['decision'] == 'approve' else 'deny'
            state['selected'] = state['choices'].index(choice)
            cli._handle_approval_selection()
        app.loop.call_soon_threadsafe(apply)


def monitor_cli():
    # The host has no CLI idle hook. Find its live UI once, retain only a weak
    # reference, then read two fields; do not wrap or modify host methods.
    reference = None
    previous = None
    questions = QuestionMonitor()
    approvals = ApprovalMonitor()
    model_spec = importlib.util.spec_from_file_location('opendeck_model_dials', ROOT+'/tools/hermes_model_dials.py')
    model_module = importlib.util.module_from_spec(model_spec)
    model_spec.loader.exec_module(model_module)
    models = model_module.ModelMonitor(bridge)
    while True:
        cli = reference() if reference else None
        if cli is None:
            cli = next((obj for obj in gc.get_objects()
                        if type(obj).__name__ == 'HermesCLI' and type(obj).__module__ == 'cli'), None)
            if cli is not None:
                reference = weakref.ref(cli)
        snapshot = ui_snapshot(cli) if cli is not None else None
        if cli is not None:
            questions.tick(cli)
            approvals.tick(cli)
            try:
                models.tick(cli)
            except Exception:
                pass  # Model controls must never stop telemetry/approval monitoring.
        else:
            questions.clear()
            approvals.clear()
        if snapshot:
            session, active = snapshot
            event = ('start' if active else 'stop') if snapshot != previous else 'heartbeat'
            publish('hermes', session, event, pid=os.getpid(), ui_active=active, ui_updated=time.time(),
                    model=getattr(getattr(cli, 'agent', None), 'model', None), native_tps=ui_throughput(cli),
                    **ui_context(cli))
            previous = snapshot
        cli = None
        time.sleep(1 if reference else 3)


def register(ctx):
    limits = {}
    # Publish presence immediately, even before the first prompt/session hook.
    if sys.stdin.isatty():
        publish('hermes', f'pid-{os.getpid()}', 'session', pid=os.getpid())
        threading.Thread(target=monitor_cli, daemon=True, name='opendeck-cli-status').start()

    def observe(event, **kwargs):
        if not sys.stdin.isatty():
            return
        session = kwargs.get('session_id') or kwargs.get('session_key') or f'pid-{os.getpid()}'
        fields = {'model': kwargs['model']} if kwargs.get('model') else {}
        if event == 'busy' and kwargs.get('model'):
            from agent.model_metadata import get_model_context_length
            from hermes_cli.config import load_config
            config = load_config()
            model_config = config.get('model', {})
            explicit = model_config.get('context_length') if isinstance(model_config, dict) else None
            key = (kwargs['model'], kwargs.get('base_url', ''), kwargs.get('provider', ''), explicit)
            if key not in limits:
                limits[key] = get_model_context_length(key[0], base_url=key[1], provider=key[2], config_context_length=explicit)
            fields.update(context_used=kwargs.get('approx_input_tokens'), context_limit=limits[key])
        if event == 'usage':
            usage = kwargs.get('usage') or {}
            if usage.get('total_tokens') is not None:
                fields['context_used'] = usage['total_tokens']
        publish('hermes', session, event, pid=os.getpid(), **fields)

    for name, event in [('on_session_start', 'session'), ('pre_llm_call', 'start'),
                        ('pre_api_request', 'busy'),
                        ('post_api_request', 'usage'),
                        ('post_llm_call', 'stop'), ('on_session_end', 'end'),
                        ('agent_loop_stopped', 'stop')]:
        ctx.register_hook(name, lambda _event=event, **kwargs: observe(_event, **kwargs))

    def stream_ended(**kwargs):
        if kwargs.get('error') or not kwargs.get('finished', True):
            observe('stop', **kwargs)

    ctx.register_hook('on_stream_end', stream_ended)

    def present(request):
        if request.surface != 'cli' or not sys.stdin.isatty():
            raise RuntimeError('Use the builtin surface outside the local CLI')
        from tools.approval import get_current_session_key
        choice = approval_dialog('hermes', request.description+'\n\n'+request.command,
                                 timeout=max(1, request.timeout_seconds-1),
                                 session=get_current_session_key(), owner=os.getpid(),
                                 allow_tool='session' in request.allowed_choices)
        return request.respond('session' if choice == 'allow_tool' else 'once' if choice == 'approve' else 'deny')

    ctx.register_approval_transport('opendeck-cli', present)
