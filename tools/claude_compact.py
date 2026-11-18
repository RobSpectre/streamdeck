#!/usr/bin/python3
"""Type Claude Code's own /compact into the idle session the Claude keys show.

Claude has no command channel. Focus that session's GNOME Terminal, type the
command, read the prompt back, and press Enter only when the prompt holds
exactly the command; otherwise delete what was typed, leaving any draft as it was.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.agent_navigation import terminal_target
from tools.claude_dial import focus, parse_picker, session_for, terminal_text
from tools.cli_agent_bridge import desktop_session, sessions

COMMAND = '/compact'
# The input box: a `>` line directly under a rule (`╭───╮` or `────`). Menus use
# `❯` as their cursor, so a `❯` line must never count as the prompt.
RULE = re.compile(r'^\s*[╭─]─{8,}[╮─]?\s*$')
PROMPT = re.compile(r'^[\s│]*>\s?(.*?)[\s│]*$')


def prompt_line(text):
    """The text in Claude's input box, or None when no input box is showing."""
    lines = text.rstrip().splitlines()[-25:]
    for above, line in reversed(list(zip(lines, lines[1:]))):
        match = PROMPT.match(line)
        if match and RULE.match(above):
            return match.group(1).strip()
    return None


def check_settings():
    config = Path.home()/'.claude.json'
    if config.exists() and json.loads(config.read_text()).get('editorMode') == 'vim':
        raise SystemExit('Claude vim mode would read the keys as commands')
    bindings = Path.home()/'.claude/keybindings.json'
    if bindings.exists():
        for group in json.loads(bindings.read_text()).get('bindings', []):
            if group.get('context') == 'Chat' and group.get('bindings', {}).get('enter', 'chat:submit') != 'chat:submit':
                raise SystemExit('Custom Claude submit binding')


def terminal(session):
    command = terminal_target(session['pid'])
    if not command:
        raise SystemExit('Claude session has no GNOME Terminal')
    subprocess.run(command, check=True, timeout=5, stdout=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(.05)
        try:
            target = focus()
            if target.get('agent') == 'terminal' and session_for(target)['session'] == session['session']:
                break
        except Exception:
            continue
    else:
        raise SystemExit('Could not focus the Claude terminal')

    def xdotool(*args):
        if focus() != target or session_for(target)['session'] != session['session']:
            raise SystemExit('Focus or session changed')
        subprocess.run(['xdotool', *args], check=True, timeout=3)

    text = terminal_text()
    if parse_picker(text) or prompt_line(text) is None:
        raise SystemExit('Claude is not at its prompt')
    xdotool('type', '--clearmodifiers', '--delay', '15', COMMAND)
    for _ in range(20):
        time.sleep(.05)
        if prompt_line(terminal_text()) == COMMAND:
            break
    else:
        # A draft was there: the cursor sits after what was typed, so this restores it.
        xdotool('key', '--clearmodifiers', *['BackSpace']*len(COMMAND))
        raise SystemExit('Claude prompt was not empty')
    xdotool('key', '--clearmodifiers', 'Return')


def main(session_id):
    check_settings()
    session = next((s for s in sessions('claude') if s['session'] == session_id), None)
    if session is None or session.get('active'):
        raise SystemExit('Claude session is gone or busy')
    if desktop_session(Path('/proc')/str(session['pid'])):
        raise SystemExit('Claude desktop compaction needs GNOME accessibility')
    terminal(session)


if __name__ == '__main__':
    main(sys.argv[1])
