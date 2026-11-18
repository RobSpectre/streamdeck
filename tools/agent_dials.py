"""Focused-session model/reasoning dials; unavailable targets fail closed."""
import base64
from functools import lru_cache
import io
import json
from pathlib import Path
import sqlite3
import select
import subprocess
import threading
import time
import uuid
from PIL import Image, ImageDraw, ImageFont
from tools.cli_agent_bridge import CACHE, atomic, desktop_session, read, sessions
from tools.codex_telemetry import app_server_read, model_label
from tools.agent_navigation import focus_agent

ROOT = Path(__file__).resolve().parents[1]
COLORS = {'codex': '#ffffff', 'claude': '#d97757', 'hermes': '#0000f2'}
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def focus():
    return json.loads(subprocess.check_output(['/usr/bin/python3', str(ROOT/'tools/agent_dial_focus.py')],
                      text=True, timeout=4, stderr=subprocess.DEVNULL))


class Desktop:
    def __init__(self):
        self.process = None

    def request(self, **request):
        if self.process is None or self.process.poll() is not None:
            self.process = subprocess.Popen(['/usr/bin/python3', str(ROOT/'tools/agent_dial_desktop.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            self.process.stdin.write(json.dumps(request)+'\n')
            self.process.stdin.flush()
            if not select.select([self.process.stdout], [], [], 5)[0]:
                raise TimeoutError('Desktop adapter timed out')
            response = json.loads(self.process.stdout.readline())
            if 'error' in response:
                raise RuntimeError(response['error'])
            return response['result']
        except Exception:
            self.process.kill()
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None
            raise


def step(values, current, ticks):
    if not values or current not in values:
        raise ValueError('Current selection is absent from the native catalog')
    return values[max(0, min(len(values)-1, values.index(current)+ticks))]


def codex_selection(state):
    """Match the desktop composer's collaboration settings, not catalog defaults."""
    settings = (state.get('latestCollaborationMode') or {}).get('settings') or {}
    return (settings.get('model') or state.get('latestModel'),
            settings.get('reasoning_effort') if 'reasoning_effort' in settings
            else state.get('latestReasoningEffort'))


@lru_cache(maxsize=256)
def render(agent, control, value, detail):
    color = COLORS[agent]
    image = Image.new('RGB', (200, 100), '#10141b')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 199, 3), fill=color)
    draw.text((100, 17), f'{agent.upper()} · {control.upper()}', fill=color,
              font=ImageFont.truetype(FONT, 12), anchor='mm')
    # Model names stay readable on the narrow strip, using two lines if needed.
    lines = [value]
    for size in range(20, 10, -1):
        font = ImageFont.truetype(FONT, size)
        if draw.textlength(value, font=font) <= 184:
            lines = [value]
            break
        splits = [(value[:i+1].strip(), value[i+1:].strip()) for i, char in enumerate(value[:-1]) if char in ' -/']
        fitting = [pair for pair in splits if all(draw.textlength(line, font=font) <= 184 for line in pair)]
        if fitting:
            lines = min(fitting, key=lambda pair: abs(len(pair[0])-len(pair[1])))
            break
    else:
        text = value
        while text and draw.textlength(text+'…', font=font) > 184:
            text = text[:-1]
        lines = [text+'…']
    for i, line in enumerate(lines):
        draw.text((100, 48+(i-(len(lines)-1)/2)*21), line, font=font, fill='white', anchor='mm')
    draw.text((100, 84), detail[:28].upper(), font=ImageFont.truetype(FONT, 10), fill=color, anchor='mm')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return {'background': 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}


def focused_cli(agent, target):
    if target.get('agent') != 'terminal':
        raise ValueError('Focus the agent terminal')
    found = []
    newest = {}
    for session in sorted(sessions(agent), key=lambda s: s.get('updated', 0)):
        newest[session['pid']] = session
    for session in newest.values():
        try:
            raw = (Path('/proc')/str(session['pid'])/'environ').read_bytes()
            env = dict(v.split(b'=', 1) for v in raw.split(b'\0') if b'=' in v)
            screen = env.get(b'GNOME_TERMINAL_SCREEN', b'').decode().rsplit('/', 1)[-1].replace('_', '-')
            stat = (Path('/proc')/str(session['pid'])/'stat').read_text().rsplit(')', 1)[1].split()
            if screen == target['screen'] and stat[2] == stat[5]:
                found.append(session)
        except (OSError, ValueError):
            pass
    if len(found) != 1:
        raise ValueError('No unique agent session in focused terminal')
    return found[0]


class AgentDials:
    def __init__(self, codex):
        self.codex = codex
        self.desktop = Desktop()
        self.focus = lambda: self.desktop.request(action='focus')
        self.models = []
        self.catalog_at = 0
        self.loading = False
        self.errors = {}
        self.display_sessions = {}

    def catalog(self):
        if time.monotonic()-self.catalog_at > 300 and not self.loading:
            self.loading = True
            def load():
                try:
                    data, cursor = [], None
                    for _ in range(10):
                        result = app_server_read('model/list', {'cursor': cursor, 'limit': 100, 'includeHidden': False})
                        data.extend(result['data'])
                        cursor = result.get('nextCursor')
                        if not cursor:
                            self.models, self.catalog_at = data, time.monotonic()
                            break
                except Exception:
                    self.catalog_at = time.monotonic()-270
                finally:
                    self.loading = False
            threading.Thread(target=load, daemon=True).start()
        return self.models

    def codex_state(self, target):
        if target.get('agent') != 'codex':
            raise ValueError('Focus Codex')
        attention = self.codex()
        connected, states = attention.snapshot()
        if not connected:
            raise ValueError('Codex disconnected')
        with sqlite3.connect(f'file:{Path.home()}/.codex/state_5.sqlite?mode=ro', uri=True) as db:
            rows = db.execute("select id from threads where coalesce(nullif(name, ''), title) = ? and archived = 0", (target['title'],)).fetchall()
        # Do not disambiguate duplicate titles by recency or activity.
        if len(rows) != 1 or rows[0][0] not in states:
            raise ValueError('Ambiguous focused Codex task')
        thread = rows[0][0]
        return thread, states[thread]

    def display_state(self, agent, target):
        """Choose a read-only display source. Mutation paths never use this fallback."""
        if agent == 'codex':
            self.catalog()
            connected, states = self.codex().snapshot()
            if not connected or not states:
                return {'model': '—', 'reasoning': '—', 'detail': 'OFFLINE'}
            try:
                identity, state = self.codex_state(target)
                self.display_sessions[agent] = identity
                detail = 'FOCUSED TASK'
            except Exception:
                identity = self.display_sessions.get(agent)
                if identity not in states:
                    identity = max(states, key=lambda k: (
                        (states[k].get('threadRuntimeStatus') or {}).get('type') == 'active',
                        states[k].get('updatedAt') or 0))
                state = states[identity]
                detail = 'FOCUS TO CHANGE' if len(states) == 1 else 'LAST TASK · FOCUS TO CHANGE'
            selected_model, effort = codex_selection(state)
            model = next((m for m in self.models if m['model'] == selected_model), {})
            return {'model': model.get('displayName') or selected_model,
                    'reasoning': effort if effort is not None else 'DEFAULT',
                    'detail': detail}
        live = {}
        for session in sorted(sessions(agent), key=lambda s: s.get('updated', 0)):
            live[session['pid']] = session
        if not live:
            return {'model': '—', 'reasoning': '—', 'detail': 'OFFLINE'}
        is_focused = False
        try:
            session = focused_cli(agent, target)
            self.display_sessions[agent] = session['session']
            is_focused = True
        except Exception:
            session = next((s for s in live.values() if s['session'] == self.display_sessions.get(agent)), None)
            if session is None:
                session = max(live.values(), key=lambda s: (bool(s.get('active')), s.get('updated', 0)))
        detail = 'FOCUSED SESSION' if is_focused else ('FOCUS TO CHANGE' if len(live) == 1 else 'LAST SESSION · FOCUS TO CHANGE')
        result = {'model': model_label(session['model']) if session.get('model') else None,
                  'reasoning': session.get('effort'), 'detail': detail}
        if agent == 'claude':
            try:
                desktop = desktop_session(Path('/proc')/str(session['pid']))
            except (OSError, ValueError, IndexError):
                desktop = False
            if desktop:
                # Only a typed /model reaches it, and that would save a new global default.
                result['detail'] = 'DESKTOP · VIEW ONLY'
            if is_focused:
                try:
                    result.update(self.claude('read', target))
                except Exception:
                    pass  # Statusline readings remain visible if the picker is closed/unavailable.
        else:
            data = read(CACHE/'models'/f"hermes-{session['pid']}.json")
            if data.get('expires', 0) >= time.time() and data.get('session') == session['session']:
                # The lab prefix (deepseek-ai/, Qwen/) is dropped, as on the telemetry keys.
                result.update(model=model_label(data.get('model')) if data.get('model') else None,
                              reasoning=data.get('reasoning') if data.get('efforts') else 'N/A')
            else:
                result.update(reasoning='RESTART HERMES', detail='MODEL LIVE · RESTART FOR DIALS')
        return result

    def snapshot(self, settings):
        focus_error = None
        try:
            target = self.focus()
        except Exception as error:
            target = {}
            focus_error = str(error)
        sources, result = {}, {}
        for s in settings:
            agent, control = s['agent'], s['parameter']
            if agent not in sources:
                try:
                    sources[agent] = self.display_state(agent, target)
                except Exception:
                    sources[agent] = {'detail': 'UNAVAILABLE'}
            source = sources[agent]
            value, detail = source.get(control), source['detail']
            if agent == 'codex' and focus_error == 'CodexAccessibilityUnavailable':
                detail = 'ENABLE ACCESSIBILITY'
            error = self.errors.get(agent)
            if error and error[0] > time.monotonic():
                detail = error[1]
            result[s['id']] = render(agent, control, str(value) if value is not None else '—', detail)
        return result

    def claude(self, action, target, parameter=None, ticks=0):
        return self.desktop.request(action='claude', operation=action, target=target,
                                    parameter=parameter or 'model', ticks=ticks)

    def rotate(self, s, ticks):
        agent, parameter = s['agent'], s['parameter']
        stage = 'FOCUS '+agent.upper()
        try:
            target = self.focus()
            if agent == 'codex':
                thread, state = self.codex_state(target)
                models = self.catalog()
                current, effort = codex_selection(state)
                model = step([m['model'] for m in models], current, ticks) if parameter == 'model' else current
                spec = next(m for m in models if m['model'] == model)
                levels = [r['reasoningEffort'] for r in spec['supportedReasoningEfforts']]
                if parameter == 'reasoning':
                    stage = 'REASONING UNAVAILABLE'
                    effort = step(levels, effort, ticks)
                elif effort not in levels:
                    effort = spec['defaultReasoningEffort']
                stage = 'FOCUS CHANGED'
                if self.focus() != target:
                    raise RuntimeError('Focus changed')
                fresh_thread, fresh_state = self.codex_state(target)
                if fresh_thread != thread or codex_selection(fresh_state) != codex_selection(state):
                    raise RuntimeError('Focused task settings changed')
                stage = 'CODEX NOT CONFIRMED'
                if model != current or effort != codex_selection(state)[1]:
                    self.codex().update_model_settings(thread, model, effort, fresh_state)
                # This is acknowledged state, never an optimistic preview. The
                # caller can render it without waiting for unrelated telemetry.
                self.errors.pop(agent, None)
                return {f'dial:codex:{parameter}': render('codex', parameter, value, 'FOCUSED TASK')
                        for parameter, value in [('model', spec.get('displayName') or model), ('reasoning', effort)]}
            else:
                stage = 'FOCUS '+agent.upper()+' SESSION'
                session = focused_cli(agent, target)
                if agent == 'claude':
                    self.claude('rotate', target, parameter, ticks)
                else:
                    data = read(CACHE/'models'/f"hermes-{session['pid']}.json")
                    stage = 'RESTART HERMES'
                    if data.get('expires', 0) < time.time() or data.get('session') != session['session']:
                        raise ValueError('Hermes not ready')
                    stage = 'HERMES BUSY'
                    if data.get('busy'):
                        raise ValueError('Hermes busy')
                    values = data.get('models' if parameter == 'model' else 'efforts', [])
                    stage = 'NO SUPPORTED CHOICES' if not values else 'UNKNOWN CURRENT VALUE'
                    selected = step(values, data.get(parameter), ticks)
                    stage = 'FOCUS CHANGED'
                    if self.focus() != target:
                        raise RuntimeError('Focus changed')
                    request = uuid.uuid4().hex
                    atomic(CACHE/'model-requests'/f"{request}.json", {
                        'request': request, 'pid': session['pid'], 'session': session['session'],
                        'signature': data['signature'], 'expires': time.time()+5,
                        'parameter': parameter, 'value': selected, 'focus': target})
            self.errors.pop(agent, None)
        except Exception as error:
            if str(error) == 'CodexAccessibilityUnavailable':
                stage = 'ENABLE ACCESSIBILITY'
            self.errors[agent] = (time.monotonic()+3, stage)
            print(f'Agent dial {agent}/{parameter} rejected: {stage}', flush=True)
            raise

    def tap(self, s):
        agent = s['agent']
        try:
            target = self.focus()
            if agent == 'codex':
                already_focused = target.get('agent') == 'codex'
            else:
                focused_cli(agent, target)
                already_focused = True
        except Exception:
            already_focused = False
        if not already_focused:
            focus_agent(agent)
            self.errors.pop(agent, None)
            return
        if agent == 'claude':
            # A focus tap never also commits a preview in a different window.
            # Busy sessions still accept a focus/no-op tap, without sending keys.
            if not focused_cli(agent, target).get('active'):
                self.claude('confirm', target)
