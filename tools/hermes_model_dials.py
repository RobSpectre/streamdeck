"""Loaded by the Hermes plugin: scoped native model changes and compaction, never global defaults."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def signature(cli, session):
    data = [session, cli.model, cli.provider, cli.reasoning_config]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def supported_efforts(provider, model):
    """Use host capability metadata and its wire adapters; unknown stays unavailable."""
    if provider in ('openrouter', 'nous'):
        # The serving catalog knows new routed models before models.dev does.
        # Its explicit ladder must not be gated by that secondary inventory.
        from hermes_cli import models_reasoning_caps as caps
        getattr(caps, 'warm_'+provider+'_reasoning_caps_async')()
        reader = getattr(caps, provider+'_model_reasoning_capabilities')
        detail = reader(model)
        # Hermes accepts case-insensitive catalog IDs, but this native reader
        # uses exact dictionary keys (e.g. Kimi-K3.1-Pro vs kimi-k3.1-pro).
        # Preserve an explicit exact-match verdict, including unsupported.
        if detail is None and model != model.lower():
            detail = reader(model.lower())
        detail = detail or {}
        return list(detail.get('supported_efforts') or []) if detail.get('supports_reasoning') is True else []
    from agent.models_dev import get_model_capabilities
    from agent import reasoning_effort as efforts
    from providers import get_provider_profile
    profile = get_provider_profile(provider)
    if profile is not None and profile.name == 'nebius-token-factory':
        # Exercise the host's pure kwargs adapter, not an API call. It owns both
        # the model-family support rule and the supported wire effort ladder.
        return [level for level in efforts.NEBIUS_EFFORTS
                if profile.build_api_kwargs_extras(model=model, reasoning_config={'effort': level})[1]
                .get('reasoning_effort') == level]
    metadata = get_model_capabilities(provider, model)
    if metadata is None or not metadata.supports_reasoning:
        return []
    if provider == 'nebius':
        return list(efforts.NEBIUS_EFFORTS)
    if provider in ('openai-codex', 'openai'):
        return list(efforts.codex_supported_efforts(model))
    if provider in ('moonshot', 'kimi-coding'):
        return list(efforts.kimi_supported_efforts(model))
    return []


def busy(cli):
    return bool(cli._agent_running or any(getattr(cli, field, None) for field in
                ('_clarify_state', '_approval_state', '_model_picker_state', '_slash_confirm_state')))


class ModelMonitor:
    def __init__(self, bridge):
        self.bridge = bridge
        self.models = []
        self.loaded = 0
        self.loading = False
        self.provider = None
        self.pending = False

    def compact(self, cli, session):
        """Queue native /compress exactly as Enter at an idle prompt would; drafts stay put."""
        for path in (self.bridge.CACHE/'compact-requests').glob('*.json'):
            request = self.bridge.read(path)
            if request.get('pid') != os.getpid():
                continue
            path.unlink(missing_ok=True)
            if request.get('expires', 0) < time.time() or not re.fullmatch(r'[0-9a-f]{32}', str(request.get('request'))):
                continue  # The deck has already given up on it.
            status = ('session changed' if request.get('session') != session else
                      'busy' if busy(cli) or self.pending else
                      'unsupported' if not hasattr(cli, '_pending_input') else 'queued')
            if status == 'queued':
                cli._pending_input.put('/compress')
            self.bridge.atomic(self.bridge.CACHE/'compact-results'/(request['request']+'.json'),
                               {'request': request['request'], 'status': status})

    def tick(self, cli):
        app = getattr(cli, '_app', None)
        session = getattr(getattr(cli, 'agent', None), 'session_id', None) or getattr(cli, 'session_id', None)
        if not session or not app or not getattr(app, 'loop', None):
            return
        session = str(session)
        try:
            self.compact(cli, session)
        except Exception:
            pass  # Compaction requests must never stop the model controls.
        provider, model = cli.provider, cli.model
        if (self.provider != provider or time.monotonic()-self.loaded > 300) and not self.loading:
            self.loading = True
            def load():
                try:
                    from hermes_cli.inventory import load_picker_context, build_models_payload
                    ctx = load_picker_context().with_overrides(current_provider=provider, current_model=model,
                                                               current_base_url=cli.base_url or '')
                    payload = build_models_payload(ctx, include_unconfigured=False, probe_custom_providers=False,
                                                   probe_current_custom_provider=False, for_picker=True)
                    rows = [r for r in payload['providers'] if r.get('slug') == provider]
                    self.models = list(dict.fromkeys(rows[0].get('models', []))) if len(rows) == 1 else []
                    self.provider, self.loaded = provider, time.monotonic()
                except Exception:
                    self.loaded = time.monotonic()-270
                finally:
                    self.loading = False
            threading.Thread(target=load, daemon=True).start()
        config = cli.reasoning_config or {}
        reasoning = 'none' if config.get('enabled') is False else config.get('effort', 'default')
        try:
            levels = supported_efforts(provider, model)
        except Exception:
            levels = []
        sig = signature(cli, session)
        available = self.models if self.provider == provider else []
        self.bridge.atomic(self.bridge.CACHE/'models'/f'hermes-{os.getpid()}.json', {
            'pid': os.getpid(), 'session': session, 'expires': time.time()+3,
            'signature': sig, 'model': model, 'reasoning': reasoning,
            'models': available, 'efforts': levels, 'busy': busy(cli) or self.pending})
        for path in (self.bridge.CACHE/'model-requests').glob('*.json'):
            request = self.bridge.read(path)
            if request.get('pid') != os.getpid():
                continue
            path.unlink(missing_ok=True)
            parameter = request.get('parameter')
            values = available if parameter == 'model' else levels if parameter == 'reasoning' else []
            if (request.get('expires', 0) < time.time() or request.get('session') != session
                    or request.get('signature') != sig or request.get('value') not in values
                    or busy(cli) or self.pending):
                continue
            self.pending = True
            def apply(request=request, sig=sig, session=session):
                worker_started = False
                try:
                    current_session = getattr(getattr(cli, 'agent', None), 'session_id', None) or getattr(cli, 'session_id', None)
                    if (request['expires'] < time.time() or str(current_session) != session
                            or signature(cli, session) != sig or busy(cli)):
                        return
                    target = json.loads(subprocess.check_output(['/usr/bin/python3', str(ROOT/'tools/agent_dial_focus.py')],
                                        text=True, timeout=4, stderr=subprocess.DEVNULL))
                    if target != request['focus']:
                        return
                    if request['parameter'] == 'model':
                        # Retain native resolution, confirmation, session persistence and
                        # rollback. Own the worker lifetime so rapid turns cannot race swaps.
                        def switch():
                            try:
                                from hermes_cli.inventory import load_picker_context
                                from hermes_cli.cli_model_switch_mixin import _switch_model_from, _merge_preflight_warning
                                ctx = load_picker_context()
                                result = _switch_model_from(cli, request['value'], is_global=False,
                                    explicit_provider=cli.provider, user_providers=ctx.user_providers,
                                    custom_providers=ctx.custom_providers)
                                if not result.success or signature(cli, session) != sig or busy(cli) or request['expires'] < time.time():
                                    return
                                check = json.loads(subprocess.check_output(['/usr/bin/python3', str(ROOT/'tools/agent_dial_focus.py')],
                                    text=True, timeout=4, stderr=subprocess.DEVNULL))
                                if check != request['focus']:
                                    return
                                _merge_preflight_warning(cli, result, ctx.custom_providers)
                                cli._confirm_and_apply_cli_model_switch(result, False, False, ctx.custom_providers)
                            finally:
                                self.pending = False
                        threading.Thread(target=switch, daemon=True).start()
                        worker_started = True
                    else:
                        from hermes_cli.cli_model_switch_mixin import _apply_reasoning_after_switch
                        _apply_reasoning_after_switch(cli, request['value'], persist_global=False)
                        app.invalidate()
                finally:
                    if not worker_started:
                        self.pending = False
            app.loop.call_soon_threadsafe(apply)
