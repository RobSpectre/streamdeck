"""Open an isolated Hermes demo terminal; never switch the workstation's profile.

The legacy public name/state indexes keep the existing physical key identity.
Demo containers have no host mounts, forwarded secrets, or Docker socket. Closing
its shell ends a demo; a subsequent launch creates a fresh container from the image.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'opendeck-hermes-demo:1'
CONTAINER = 'opendeck-hermes-demo'
LABEL = 'party.hack.opendeck.hermes-demo'
DOCKER = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock']
STATES = {'fresh': 0, 'unavailable': 1, 'config': 2}
MODES = ('config', 'fresh')
_status_cache = None


def control_root():
    return Path.home()/'.cache/opendeck-agents/hermes-demo'


def run(*args, **kwargs):
    return subprocess.run([*DOCKER, *args], check=True, text=True,
                          capture_output=True, timeout=8, **kwargs)


def inspect(kind, name):
    result = subprocess.run([*DOCKER, kind, 'inspect', name], text=True,
                            capture_output=True, timeout=8)
    if result.returncode:
        if 'No such' in result.stderr:
            return None
        raise RuntimeError('Docker is unavailable; the workstation Hermes was not changed.')
    return json.loads(result.stdout)[0]


def managed_container():
    value = inspect('container', CONTAINER)
    if value is not None and value.get('Config', {}).get('Labels', {}).get(LABEL) != '1':
        raise RuntimeError('Demo container name belongs to another container; refusing to change it.')
    return value


def read_selection(root=None):
    try:
        return json.loads(((root or control_root())/'selection.json').read_text())
    except (OSError, ValueError):
        return {}


def write_selection(value, root=None):
    root = root or control_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = root/'selection.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
    temporary.replace(root/'selection.json')
    invalidate()


def invalidate():
    global _status_cache
    _status_cache = None


@contextmanager
def locked(root=None):
    root = root or control_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root/'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def available(root=None):
    return inspect('image', IMAGE) is not None


def mode(root=None):
    selected = read_selection(root)
    if selected.get('mode') != 'fresh':
        return 'config'
    container = managed_container()
    # A newly opened terminal has a short start window before Docker is attached.
    running = container and container['State']['Running']
    starting = container and container['State']['Status'] == 'created' and time.time()-selected.get('started', 0) < 15
    return 'fresh' if running or starting else 'config'


def state(root=None):
    global _status_cache
    now = time.monotonic()
    if _status_cache and _status_cache[0] == root and now-_status_cache[1] < 5:
        return _status_cache[2]
    try:
        value = STATES[mode(root)] if available(root) else STATES['unavailable']
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, RuntimeError):
        value = STATES['unavailable']
    _status_cache = (root, now, value)
    return value


def create_command():
    # Explicit isolation: no volumes, mounts, env forwarding, host networking,
    # privileged mode, host PID namespace, devices, or desktop/Docker sockets.
    return ['create', '--name', CONTAINER, '--label', LABEL+'=1',
            '--hostname', 'hermes-demo', '--interactive', '--tty',
            '--user', '10001:10001', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '512',
            '--memory', '8g', '--cpus', '4', '--network', 'bridge', IMAGE]


def discard_stopped():
    value = managed_container()
    if value:
        if value['State']['Status'] not in ('created', 'exited', 'dead') or value['State']['Running']:
            raise RuntimeError('Exit the demo shell before resetting it; a running demo is never killed.')
        run('rm', value['Id'])


def focus_demo(selected):
    from tools.agent_navigation import terminal_target
    pid = selected.get('terminal_pid')
    if not isinstance(pid, int):
        raise RuntimeError('Demo terminal is starting; try the button again shortly.')
    # Guard against a recycled PID. Only our dedicated attach helper can be focused.
    args = Path('/proc', str(pid), 'cmdline').read_bytes().split(b'\0')
    if str(Path(__file__).resolve()).encode() not in args or b'--attach' not in args:
        raise RuntimeError('Demo terminal is unavailable; close it before starting a new demo.')
    command = terminal_target(pid)
    if not command:
        raise RuntimeError('Cannot identify the demo terminal.')
    subprocess.run(command, check=True, timeout=5, stdout=subprocess.DEVNULL)


def set_mode(root, name):
    if name not in MODES:
        raise ValueError('Expected config or fresh')
    with locked(root):
        selected = read_selection(root)
        if name == 'config':
            from tools.agent_navigation import focus_agent
            try:
                focus_agent('hermes')
            except RuntimeError:
                subprocess.run(['/usr/bin/gnome-terminal', '--title=Hermes — My Config', '--',
                                str(Path.home()/'.local/bin/hermes'), '-p', 'default'],
                               check=True, timeout=8)
            write_selection({**selected, 'mode': 'config'}, root)
            return name
        if not available(root):
            raise RuntimeError('Prepare the demo image with tools/hermes_config.py --ensure first.')
        value = managed_container()
        if value and value['State']['Running']:
            focus_demo(selected)
            write_selection({**selected, 'mode': 'fresh'}, root)
            return name
        if value and value['State']['Status'] == 'created' and time.time()-selected.get('started', 0) < 15:
            raise RuntimeError('Demo terminal is starting.')
        discard_stopped()
        run(*create_command())
        write_selection({'mode': 'fresh', 'started': time.time()}, root)
        try:
            subprocess.run(['/usr/bin/gnome-terminal', '--title=Hermes Demo — Isolated', '--',
                            sys.executable, str(Path(__file__).resolve()), '--attach'],
                           check=True, timeout=8)
        except Exception:
            discard_stopped()
            write_selection({'mode': 'config'}, root)
            raise
    return name


def toggle(root=None):
    return set_mode(root, 'config' if mode(root) == 'fresh' else 'fresh')


def ensure(root=None):
    if available(root):
        return False
    subprocess.run([*DOCKER, 'build', '--target', 'ready', '-t', IMAGE,
                    str(ROOT/'integrations/hermes-demo')], check=True)
    invalidate()
    return True


def attach():
    with locked():
        value = managed_container()
        if not value or value['State']['Status'] != 'created':
            raise RuntimeError('No new managed demo is waiting to start.')
        selected = read_selection()
        write_selection({**selected, 'terminal_pid': os.getpid()})
        identifier = value['Id']
    # Attached only to this exact newly-created container, never an arbitrary name.
    result = subprocess.run([*DOCKER, 'start', '--attach', '--interactive', identifier])
    invalidate()
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--status', action='store_true')
    actions.add_argument('--state', action='store_true')
    actions.add_argument('--toggle', action='store_true')
    actions.add_argument('--mode', choices=MODES)
    actions.add_argument('--ensure', action='store_true', help='build the isolated clean Hermes image')
    actions.add_argument('--reset', action='store_true', help='discard a stopped demo; never stop a running one')
    actions.add_argument('--attach', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.attach:
        return attach()
    if args.ensure:
        print('Demo image built.' if ensure() else 'Demo image ready.')
    elif args.reset:
        with locked():
            discard_stopped()
            write_selection({'mode': 'config'})
        print('Next demo will start clean.')
    elif args.toggle or args.mode:
        print(toggle() if args.toggle else set_mode(None, args.mode))
    elif args.state:
        print(state())
    else:
        print(mode())
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
