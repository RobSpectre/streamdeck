"""Deck-requested compaction: each agent's own command, for the session its keys show."""
from pathlib import Path
import subprocess
import time
import uuid

from tools.agent_telemetry import displayed
from tools.cli_agent_bridge import CACHE, atomic, read, sessions
from tools.codex_attention import needs_input
from tools.codex_telemetry import displayed_thread

ROOT = Path(__file__).resolve().parents[1]


def codex(attention):
    """Ask the desktop app that owns the shown task to run its manual compaction."""
    if attention is None:
        raise RuntimeError('Codex is not followed')
    connected, states = attention.snapshot()
    thread, state = displayed_thread(states if connected else {})
    if thread is None:
        raise RuntimeError('No Codex task')
    if state.get('threadRuntimeStatus', {}).get('type') == 'active' or needs_input(state):
        raise RuntimeError('Codex is busy')
    attention.compact_thread(thread)


def hermes():
    """Hand /compress to the plugin inside the shown Hermes CLI, which rechecks idle."""
    current = displayed(sessions('hermes'))
    if not current:
        raise RuntimeError('No Hermes session')
    if current.get('active'):
        raise RuntimeError('Hermes is busy')
    request = uuid.uuid4().hex
    path, result = CACHE/'compact-requests'/(request+'.json'), CACHE/'compact-results'/(request+'.json')
    atomic(path, {'request': request, 'pid': current['pid'], 'session': current['session'],
                  'expires': time.time()+3})
    try:
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            status = read(result).get('status')
            if status == 'queued':
                return
            if status:
                raise RuntimeError('Hermes refused compaction: '+status)
            time.sleep(.05)
        raise RuntimeError('No answer from Hermes; restart it to load compaction')
    finally:
        path.unlink(missing_ok=True)
        result.unlink(missing_ok=True)


def claude():
    """Claude has no command channel: a system-Python helper types /compact and checks it."""
    current = displayed(sessions('claude'))
    if not current:
        raise RuntimeError('No Claude session')
    if current.get('active'):
        raise RuntimeError('Claude is busy')
    subprocess.run(['/usr/bin/python3', str(ROOT/'tools/claude_compact.py'), current['session']],
                   check=True, timeout=12)


def compact(agent, attention=None):
    if agent == 'codex':
        codex(attention)
    elif agent == 'hermes':
        hermes()
    elif agent == 'claude':
        claude()
    else:
        raise ValueError('Unknown agent')
