"""User-pressed telemetry navigation: focus existing agents or open account pages."""
import json
from pathlib import Path
import re
import subprocess
import time
import uuid
from tools.cli_agent_bridge import sessions

ROOT = Path(__file__).resolve().parents[1]


def windows():
    listing = subprocess.check_output(['xprop', '-root', '_NET_CLIENT_LIST_STACKING'], text=True)
    result = []
    for window in reversed(re.findall(r'0x[0-9a-fA-F]+', listing)):
        try:
            props = subprocess.check_output(['xprop', '-id', window, 'WM_CLASS', '_NET_WM_PID'], text=True, stderr=subprocess.DEVNULL)
            result.append((window, props))
        except subprocess.CalledProcessError:
            continue
    return result


def terminal_target(pid):
    """Read only the window/session identifiers inherited by this CLI process."""
    raw = (Path('/proc')/str(pid)/'environ').read_bytes()
    env = dict(value.split(b'=', 1) for value in raw.split(b'\0') if b'=' in value)
    screen = env.get(b'GNOME_TERMINAL_SCREEN', b'').decode()
    if screen.startswith('/org/gnome/Terminal/screen/'):
        identifier = str(uuid.UUID(screen.rsplit('/', 1)[1].replace('_', '-')))
        service = env.get(b'GNOME_TERMINAL_SERVICE', b'org.gnome.Terminal').decode()
        if not re.fullmatch(r':[0-9]+\.[0-9]+|org\.gnome\.Terminal', service):
            raise ValueError('Invalid terminal service')
        return ['gdbus', 'call', '--session', '--dest', service,
                '--object-path', '/org/gnome/Terminal/SearchProvider', '--method',
                'org.gnome.Shell.SearchProvider2.ActivateResult', identifier, '[]', str(int(time.monotonic()*1000) & 0xffffffff)]
    window = env.get(b'WINDOWID', b'').decode()
    if window.isdigit() and int(window):
        return ['xdotool', 'windowactivate', '--sync', window]
    return None


def cli_pids(agent):
    live = sorted(sessions(agent), key=lambda v: (v.get('active', False), v['updated']), reverse=True)
    pids = list(dict.fromkeys(v['pid'] for v in live))
    # A CLI opened before the hooks were installed still has a terminal to focus.
    for path in Path('/proc').glob('[0-9]*'):
        try:
            args = path.joinpath('cmdline').read_bytes().split(b'\0')
            stat = path.joinpath('stat').read_text().rsplit(')', 1)[1].split()
            if int(stat[4]) == 0:
                continue
            match = (agent == 'hermes' and str(Path.home()/'.hermes/hermes-agent/hermes').encode() in args[:2]) or (agent == 'claude' and path.joinpath('comm').read_text().strip() == 'claude')
            if match and int(path.name) not in pids:
                pids.append(int(path.name))
        except (OSError, ValueError, IndexError):
            continue
    return pids


def focus_agent(agent):
    if agent == 'codex':
        for window, props in windows():
            if '"Chatgpt"' in props and '/.config/Codex)' in props:
                subprocess.run(['xdotool', 'windowactivate', '--sync', window], check=True, timeout=5)
                return
    elif agent in ('claude', 'hermes'):
        for pid in cli_pids(agent):
            try:
                command = terminal_target(pid)
                if command:
                    subprocess.run(command, check=True, timeout=5, stdout=subprocess.DEVNULL)
                    return
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
    raise RuntimeError(f'No running {agent} window found')


def activate(agent, metric):
    if metric in ('activity', 'context', 'session'):
        focus_agent(agent)
    elif metric in ('speed', 'month'):
        links = json.loads((ROOT/'agent-navigation.json').read_text())
        url = links[agent]['activity' if metric == 'speed' else 'billing']
        if not url.startswith('https://'):
            raise ValueError('Account links must use HTTPS')
        subprocess.Popen(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
