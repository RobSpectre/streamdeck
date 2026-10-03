#!/usr/bin/python3
"""System-Python D-Bus adapters for broadcast dials; never auto-start apps."""
import argparse
import json
import math
import re
import subprocess
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.suno_media import dbus_call, unique


def spotify(ticks=0):
    from gi.repository import GLib
    names = dbus_call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                      'org.freedesktop.DBus', 'ListNames')[0]
    name = unique([n for n in names if n == 'org.mpris.MediaPlayer2.spotify'
                   or n.startswith('org.mpris.MediaPlayer2.spotify.')], 'Spotify instance')
    owner = dbus_call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                      'org.freedesktop.DBus', 'GetNameOwner', '(s)', (name,))[0]
    path, interface = '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player'
    value = float(dbus_call(owner, path, 'org.freedesktop.DBus.Properties',
                            'Get', '(ss)', (interface, 'Volume'))[0])
    if not math.isfinite(value):
        raise ValueError('Invalid Spotify volume')
    if ticks:
        value = max(0, min(1, value + ticks * .02))
        dbus_call(owner, path, 'org.freedesktop.DBus.Properties', 'Set', '(ssv)',
                  (interface, 'Volume', GLib.Variant('d', value)))
        value = float(dbus_call(owner, path, 'org.freedesktop.DBus.Properties',
                                'Get', '(ss)', (interface, 'Volume'))[0])
    return {'value': value * 100}


def command(*args):
    return subprocess.check_output(args, text=True, timeout=2, stderr=subprocess.DEVNULL).strip()


def focused():
    window = command('xdotool', 'getactivewindow')
    if not window.isdecimal():
        raise ValueError('Invalid focused window')
    props = command('xprop', '-id', window, 'WM_CLASS', '_GTK_UNIQUE_BUS_NAME', '_GTK_WINDOW_OBJECT_PATH')
    fields = {}
    for line in props.splitlines():
        name = line.split('(', 1)[0]
        fields[name] = re.findall(r'"([^"\n]*)"', line)
    return window, fields


def window_control(kind, ticks=0):
    window, fields = focused()
    classes = fields.get('WM_CLASS', [])
    terminal = 'Gnome-terminal' in classes
    if kind == 'terminal_font' and not terminal:
        raise ValueError('Focus GNOME Terminal')
    supported = terminal or bool(set(classes) & {'Google-chrome', 'Chromium', 'firefox', 'Firefox', 'Code', 'code', 'Chatgpt', 'Codex'})
    if not supported:
        raise ValueError('Unsupported focused app')
    if ticks:
        for _ in range(min(abs(ticks), 20)):
            if focused() != (window, fields):
                raise RuntimeError('Focus changed')
            if terminal:
                bus = unique(fields.get('_GTK_UNIQUE_BUS_NAME', []), 'terminal bus')
                path = unique(fields.get('_GTK_WINDOW_OBJECT_PATH', []), 'terminal window')
                if not re.fullmatch(r':[0-9]+\.[0-9]+', bus) or not re.fullmatch(r'/org/gnome/Terminal/window/[0-9]+', path):
                    raise ValueError('Invalid terminal endpoint')
                dbus_call(bus, path, 'org.gtk.Actions', 'Activate', '(sava{sv})',
                          ('zoom-in' if ticks > 0 else 'zoom-out', [], {}))
            else:
                # XTEST delivers native shortcuts, with focus checked for each step.
                command('xdotool', 'key', '--clearmodifiers', 'ctrl+plus' if ticks > 0 else 'ctrl+minus')
    return {'value': None, 'detail': 'GNOME TERMINAL' if terminal else 'FOCUSED APP'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['spotify', 'terminal_font', 'window_zoom'])
    parser.add_argument('ticks', type=int, nargs='?', default=0)
    args = parser.parse_args()
    try:
        result = spotify(args.ticks) if args.kind == 'spotify' else window_control(args.kind, args.ticks)
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'error': type(error).__name__}))
        sys.exit(1)
