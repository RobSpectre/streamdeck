#!/usr/bin/env python3
"""Send the Codex approval shortcut only to the focused Codex desktop window."""
import argparse
import subprocess
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.cli_agent_bridge import respond_focused, respond_question


def codex_focused():
    try:
        window = subprocess.check_output(['xdotool', 'getactivewindow'], text=True).strip()
        identity = subprocess.check_output(['xprop', '-id', window, 'WM_CLASS'], text=True)
        return window if '"Chatgpt"' in identity and '/.config/Codex)' in identity else None
    except subprocess.SubprocessError:
        return None


def dictate():
    window = codex_focused()
    if window and subprocess.check_output(['xdotool', 'getactivewindow'], text=True).strip() == window:
        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+shift+d'], check=True)


def respond(decision, codex_ready=None):
    window = subprocess.check_output(['xdotool', 'getactivewindow'], text=True).strip()
    identity = subprocess.check_output(['xprop', '-id', window, 'WM_CLASS', '_NET_WM_NAME', '_NET_WM_PID'], text=True)
    if respond_focused(decision, window, identity):
        return
    if not codex_ready and '"Chatgpt"' not in identity and respond_question(decision):
        return
    # This Linux app uses Chatgpt as its class and Codex's user-data path as instance.
    if '"Chatgpt"' not in identity or '/.config/Codex)' not in identity:
        return
    if codex_ready is None:
        from tools.codex_attention import CodexAttention
        attention = CodexAttention()
        deadline = time.monotonic()+1
        while time.monotonic() < deadline:
            connected, states = attention.snapshot()
            if connected and states:
                break
            time.sleep(.02)
        codex_ready = bool(attention.indicator())
    if not codex_ready:
        return
    if subprocess.check_output(['xdotool', 'getactivewindow'], text=True).strip() != window:
        return
    subprocess.run(['xdotool', 'key', '--clearmodifiers',
                    'Return' if decision == 'approve' else 'Escape'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('decision', choices=['approve', 'deny'])
    args = parser.parse_args()
    respond(args.decision)
