"""User-driven CLI approval dialogs and compact local telemetry snapshots."""
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

CACHE = Path.home()/'.cache/opendeck-agents'


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
    temp.replace(path)


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def publish(agent, session, event, **fields):
    key = hashlib.sha256(str(session).encode()).hexdigest()
    path = CACHE/agent/(key+'.json')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read(path)
        now = time.time()
        data.update(agent=agent, session=str(session), updated=now, **fields)
        if event == 'start':
            data.update(active=True, turn_started=now, turn_ended=None)
        elif event == 'busy':
            data.update(active=True, turn_ended=None)
        elif event in ('stop', 'end', 'error'):
            data.update(active=False, turn_ended=now)
        elif event == 'session':
            data.setdefault('active', False)
        atomic(path, data)
    return data


def sessions(agent):
    values = [read(p) for p in (CACHE/agent).glob('*.json')]
    values = [v for v in values if v and alive(v.get('pid'))]
    if agent == 'hermes':
        # /new and resumed conversations share a CLI process. Old sessions
        # must not keep the process active after its current session is idle.
        newest = {}
        for value in sorted(values, key=lambda v: v.get('updated', 0)):
            newest[value['pid']] = value
        values = list(newest.values())
        for value in values:
            if time.time()-value.get('ui_updated', 0) < 10:
                value['active'] = bool(value['ui_active'])
    return values


def pending():
    return [v for p in (CACHE/'pending').glob('*.json')
            if (v := read(p)) and v.get('expires', 0) > time.time() and alive(v.get('pid'))]


def auto_enabled():
    grant = read(CACHE/'auto.json')
    return grant if grant and alive(grant.get('owner')) else {}


def disable_auto():
    (CACHE/'auto.json').unlink(missing_ok=True)


def approval_dialog(agent, details, timeout=300, session=None, owner=None, tool_key=None, allow_tool=True):
    scope = {'agent': agent, 'session': session, 'owner': owner}
    grant = auto_enabled()
    if session and owner and all(grant.get(k) == v for k, v in scope.items()):
        return 'approve'
    rule = CACHE/'rules'/hashlib.sha256(json.dumps([scope, tool_key], sort_keys=True).encode()).hexdigest()
    if tool_key and read(rule).get('allowed'):
        return 'approve'
    if not os.environ.get('DISPLAY'):
        raise RuntimeError('No desktop display; use native CLI approval')
    request = uuid.uuid4().hex
    title = f'{agent.title()} CLI approval · {request[:8]}'
    proc = subprocess.Popen(['zenity', '--question', '--no-markup', '--width=720',
                             '--title='+title, '--text='+details,
                             '--ok-label=Approve once', '--cancel-label=Deny'],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    marker = CACHE/'pending'/(request+'.json')
    response = CACHE/'decisions'/(request+'.json')
    atomic(marker, {'request': request, 'agent': agent, 'pid': proc.pid,
                    'title': title, 'expires': time.time()+timeout, 'scope': scope,
                    'extended': bool(session and owner), 'allow_tool': allow_tool})
    try:
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            result = read(response)
            if result.get('request') == request and result.get('decision') in ('approve', 'deny', 'auto', 'allow_tool'):
                if result['decision'] == 'auto':
                    if not session or not owner:
                        continue
                    atomic(CACHE/'auto.json', scope)
                    return 'approve'
                if result['decision'] == 'allow_tool' and tool_key:
                    atomic(rule, {'allowed': True})
                    return 'approve'
                return result['decision']
            code = proc.poll()
            if code is not None:
                if code not in (0, 1, 5):
                    raise RuntimeError('Could not show approval dialog')
                return 'approve' if code == 0 else 'deny'
            time.sleep(.05)
        return 'deny'
    finally:
        marker.unlink(missing_ok=True)
        response.unlink(missing_ok=True)
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=3)


def respond_focused(decision, window, properties):
    """Match the dialog's exact PID and title; never type into an agent terminal."""
    pid = re.search(r'_NET_WM_PID[^=]*=\s*(\d+)', properties)
    for item in pending():
        if item.get('kind') == 'question':
            continue
        if decision in ('auto', 'allow_tool') and not item.get('extended'):
            continue
        if decision == 'allow_tool' and not item.get('allow_tool', False):
            continue
        if not pid or int(pid[1]) != item['pid'] or item['title'] not in properties:
            continue
        if subprocess.check_output(['xdotool', 'getactivewindow'], text=True).strip() != window:
            return False
        atomic(CACHE/'decisions'/(item['request']+'.json'), {'request': item['request'], 'decision': decision})
        return True
    return False


def respond_question(decision):
    """A physical response press can target one unambiguous native question."""
    items = pending()
    if decision not in ('approve', 'deny') or len(items) != 1 or items[0].get('kind') != 'question':
        return False
    item = items[0]
    atomic(CACHE/'decisions'/(item['request']+'.json'),
           {'request': item['request'], 'decision': decision})
    return True


def claude_owner():
    pid = os.getppid()
    for _ in range(12):
        try:
            command = (Path('/proc')/str(pid)/'cmdline').read_bytes().lower()
            if b'claude' in command and b'cli_agent_bridge.py' not in command:
                return pid
            stat = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()
            pid = int(stat[1])
        except (OSError, ValueError, IndexError):
            break
    return os.getppid()


def interactive_owner(pid):
    try:
        stat = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()
        return int(stat[4]) != 0
    except (OSError, ValueError, IndexError):
        return False


def claude_hook(payload, mode):
    event = payload.get('hook_event_name')
    session = payload.get('session_id', 'unknown')
    fields = {'pid': claude_owner(), 'transcript': payload.get('transcript_path')}
    if not interactive_owner(fields['pid']):
        return None if mode == 'status' else {}
    if mode == 'status':
        fields['model'] = (payload.get('model') or {}).get('display_name') or (payload.get('model') or {}).get('id')
        fields['rate_limits'] = payload.get('rate_limits', {})
        fields['context_remaining'] = (payload.get('context_window') or {}).get('remaining_percentage')
        fields['quota_updated'] = time.time()
        publish('claude', session, 'status', **fields)
        previous = read(CACHE/'claude-original-statusline.json')
        if previous.get('command'):
            subprocess.run(previous['command'], shell=True, input=json.dumps(payload), text=True, check=False)
        return None
    kind = {'SessionStart': 'session', 'UserPromptSubmit': 'start', 'Stop': 'stop',
            'StopFailure': 'error', 'SessionEnd': 'end'}.get(event, 'update')
    if event == 'Notification' and payload.get('notification_type') == 'idle_prompt':
        kind = 'stop'
    publish('claude', session, kind, **fields)
    if event == 'PermissionRequest':
        try:
            decision = approval_dialog('claude', payload.get('tool_name', 'Tool')+'\n\n'+
                                       json.dumps(payload.get('tool_input', {}), indent=2, ensure_ascii=False),
                                       session=session, owner=fields['pid'],
                                       tool_key=[payload.get('tool_name'), payload.get('tool_input')])
        except (OSError, RuntimeError):
            return {}  # Preserve Claude's native prompt if the desktop is unavailable.
        return {'hookSpecificOutput': {'hookEventName': 'PermissionRequest',
                'decision': {'behavior': 'allow' if decision == 'approve' else 'deny'}}}
    return {}


if __name__ == '__main__':
    result = claude_hook(json.load(sys.stdin), sys.argv[1])
    if result is not None:
        print(json.dumps(result))
