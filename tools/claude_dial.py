#!/usr/bin/python3
"""Claude 2.1.274 native picker adapter. Never sends Enter or saves defaults."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.agent_dial_focus import snapshot as focus
from tools.cli_agent_bridge import sessions


def parse_picker(text):
    # The current picker is at the bottom of the visible terminal, not scrollback.
    match = re.search(r'Select model\s+Switch between Claude models\.', text)
    if not match:
        return None
    text = text[match.start():]
    if not re.search(r's to use\s+this session only', text) or 'Esc to cancel' not in text:
        return None
    selected = re.findall(r'^\s*❯\s*\d+\.\s+(.+)$', text, re.M)
    if len(selected) != 1:
        return None
    columns = re.split(r'\s{2,}', selected[0].replace('✔', '').strip(), maxsplit=1)
    model = columns[-1].split(' · ')[0].strip() if len(columns) > 1 else columns[0]
    effort = re.search(r'\b(Low|Medium|High|xHigh|Max|Ultra(?:code)?) effort\b', text, re.I)
    unsupported = 'Effort not supported' in text
    if not effort and not unsupported:
        return None
    return {'model': model, 'reasoning': effort.group(1).upper() if effort else 'N/A',
            'detail': 'PREVIEW · TAP TO APPLY', 'supported': not unsupported}


def terminal_text():
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    from tools.suno_media import matches, unique
    Atspi.set_timeout(500, 1000)
    desktop = Atspi.get_desktop(0)
    terminals = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if not app or app.get_name() != 'gnome-terminal-server':
            continue
        app.set_cache_mask(Atspi.Cache.NONE)
        for node in matches(app, Atspi.Role.TERMINAL, Atspi):
            states = node.get_state_set()
            if states.contains(Atspi.StateType.FOCUSED) and states.contains(Atspi.StateType.SHOWING):
                terminals.append(node)
    node = unique(terminals, 'focused terminal')
    text = node.get_text_iface()
    # In Claude's alternate screen this is the visible picker; do not retain it.
    count = text.get_character_count()
    return Atspi.Text.get_text(text, max(0, count-10000), count)


def session_for(target):
    matches = []
    newest = {}
    for session in sorted(sessions('claude'), key=lambda s: s.get('updated', 0)):
        newest[session['pid']] = session
    for session in newest.values():
        try:
            pid = session['pid']
            env = dict(v.split(b'=', 1) for v in (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0') if b'=' in v)
            screen = env.get(b'GNOME_TERMINAL_SCREEN', b'').decode().rsplit('/', 1)[-1].replace('_', '-')
            stat = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()
            if screen == target.get('screen') and int(stat[2]) == int(stat[5]):
                matches.append(session)
        except (OSError, ValueError):
            pass
    if len(matches) != 1:
        raise ValueError('No foreground Claude session')
    return matches[0]


def check_bindings():
    path = Path.home()/'.claude/keybindings.json'
    if path.exists():
        data = json.loads(path.read_text())
        defaults = {'Chat': {'alt+p': 'chat:modelPicker'},
                    'ModelPicker': {'left': 'modelPicker:decreaseEffort', 'right': 'modelPicker:increaseEffort',
                                    's': 'modelPicker:thisSessionOnly'},
                    'Select': {'up': 'select:previous', 'down': 'select:next'}}
        for group in data.get('bindings', []):
            for key, action in defaults.get(group.get('context'), {}).items():
                if key in group.get('bindings', {}) and group['bindings'][key] != action:
                    raise ValueError('Custom Claude picker bindings')


def run(action, target, parameter='model', ticks=0):
    if focus() != target or target.get('agent') != 'terminal':
        raise ValueError('Focus changed')
    session = session_for(target)
    picker = parse_picker(terminal_text())
    if action == 'read':
        return picker or {'model': session.get('model'), 'reasoning': session.get('effort'), 'detail': 'FOCUSED SESSION'}
    if session.get('active'):
        raise ValueError('Claude is busy')
    check_bindings()
    def key(value):
        if focus() != target or session_for(target)['session'] != session['session']:
            raise RuntimeError('Focus or session changed')
        subprocess.run(['xdotool', 'key', '--clearmodifiers', value], check=True, timeout=2)
    if not picker:
        if action == 'confirm':
            return {}
        key('alt+p')
        for _ in range(10):
            time.sleep(.05)
            picker = parse_picker(terminal_text())
            if picker:
                break
    if not picker:
        raise ValueError('Native model picker unavailable')
    if action == 'rotate':
        if parameter == 'reasoning' and not picker['supported']:
            return picker
        for _ in range(min(abs(ticks), 20)):
            key(('Down' if ticks > 0 else 'Up') if parameter == 'model' else ('Right' if ticks > 0 else 'Left'))
        time.sleep(.08)
        picker = parse_picker(terminal_text())
        if not picker:
            raise ValueError('Picker changed')
        # Native picker caps reasoning based on highlighted model/account policy.
        return picker
    if action == 'confirm':
        key('s')
        return {}
    raise ValueError('Unknown action')


if __name__ == '__main__':
    try:
        print(json.dumps(run(sys.argv[1], json.loads(sys.argv[2]), sys.argv[3], int(sys.argv[4]))))
    except Exception:
        sys.exit(1)
