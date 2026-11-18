#!/usr/bin/env python3
"""Explicit, expiring-by-identity PulseAudio bindings for four Chrome TV players.

Chrome supplies no tab/window identity on its Playback streams. Bind only an
observed stream/window pair; never infer a tab from stream ordering or PID alone.
Browser mute must be off to retain the stream; mute/solo happens in PulseAudio.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

TITLES = ('MS NOW', 'CNN', 'FOX NEWS', 'ABC')


def run(*args):
    return subprocess.check_output(args, text=True, timeout=3, stderr=subprocess.DEVNULL)


def directory():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'opendeck-agents/television-audio'


@contextmanager
def locked():
    root = directory()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(root/'lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def process_identity(pid):
    pid = int(pid)
    # PID alone can be reused, as can PulseAudio's numeric stream indices.
    start = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()[19]
    return [pid, start, Path('/proc/sys/kernel/random/boot_id').read_text().strip()]


def streams():
    return json.loads(run('pactl', '-f', 'json', 'list', 'sink-inputs'))


def fingerprint(stream):
    props = stream.get('properties', {})
    if props.get('application.process.binary') not in ('chrome', 'chromium'):
        raise ValueError('Not a Chrome playback stream')
    serial = props.get('object.serial')
    if not str(serial or '').isdecimal():
        raise ValueError('Missing PipeWire stream serial')
    return {'index': int(stream['index']), 'client': str(stream['client']),
            'serial': str(serial), 'process': process_identity(props['application.process.id'])}


def window_identity(window):
    window = str(int(window))
    props = run('xprop', '-id', window, '_NET_WM_NAME', 'WM_CLASS', '_NET_WM_PID')
    title = next((line for line in props.splitlines() if line.startswith('_NET_WM_NAME(')), '')
    classes = next((line for line in props.splitlines() if line.startswith('WM_CLASS(')), '')
    if 'YouTube TV' not in title or not set(re.findall(r'"([^"]+)"', classes)) & {
            'google-chrome', 'Google-chrome', 'chromium', 'Chromium'}:
        raise ValueError('Bound TV window closed or navigated away')
    pid = re.search(r'_NET_WM_PID\(CARDINAL\) = (\d+)', props)
    if not pid:
        raise ValueError('Missing browser window owner')
    return {'window': window, 'process': process_identity(pid[1])}


def load():
    value = json.loads((directory()/'bindings.json').read_text())
    if value.get('version') != 1 or not isinstance(value.get('slots'), dict):
        raise ValueError('Invalid TV audio bindings')
    return value['slots']


def save(slots):
    path = directory()/'bindings.json'
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump({'version': 1, 'slots': slots}, handle)
        handle.write('\n')
    temporary.replace(path)


def slot_number(slot):
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError('Invalid television slot')
    return str(slot)


def bind(slot, stream_index, window):
    key = slot_number(slot)
    with locked():
        candidates = [s for s in streams() if s['index'] == stream_index]
        if len(candidates) != 1:
            raise ValueError('Missing or ambiguous stream')
        binding = {'stream': fingerprint(candidates[0]), 'window': window_identity(window)}
        try:
            slots = load()
        except FileNotFoundError:
            slots = {}
        for other, old in slots.items():
            if other != key and (old['stream'] == binding['stream'] or old['window'] == binding['window']):
                raise ValueError('TV stream/window already assigned to another dial')
        slots[key] = binding
        save(slots)


def resolve(binding, current):
    matches = [s for s in current if int(s['index']) == binding['stream']['index']]
    if len(matches) != 1 or fingerprint(matches[0]) != binding['stream']:
        raise ValueError('TV stream changed; rebind this player')
    if window_identity(binding['window']['window']) != binding['window']:
        raise ValueError('TV window changed; rebind this player')
    return matches[0]


def reading(slot, stream):
    volume = max(float(v['value']) / 65536 * 100 for v in stream['volume'].values())
    if not math.isfinite(volume) or type(stream['mute']) is not bool:
        raise ValueError('Invalid TV volume/mute reading')
    return {'title': TITLES[slot], 'volume': volume, 'mute': stream['mute']}


def snapshot():
    slots, current = load(), streams()
    result = {}
    for slot in range(4):
        try:
            result[slot] = reading(slot, resolve(slots[str(slot)], current))
        except (KeyError, ValueError, OSError, subprocess.SubprocessError):
            result[slot] = None
    return result


def read(slot):
    slot_number(slot)
    result = snapshot()[slot]
    if result is None:
        raise ValueError('TV audio unavailable; rebind this player')
    return result


def write(binding, command, value):
    # Re-resolve immediately before every mutation. Never use a stale index.
    stream = resolve(binding, streams())
    run('pactl', command, str(stream['index']), str(value))


def solo(slot):
    key = slot_number(slot)
    with locked():
        slots, current = load(), streams()
        if set(slots) != {'0', '1', '2', '3'}:
            raise ValueError('Bind all four TV players first')
        if len({b['stream']['index'] for b in slots.values()}) != 4:
            raise ValueError('Duplicate TV streams')
        for binding in slots.values():
            resolve(binding, current)
        # Mute the other three before making the chosen feed audible. A failure
        # leaves the target untouched; no rollback unmutes another television.
        for other, binding in slots.items():
            if other != key:
                write(binding, 'set-sink-input-mute', 1)
        current = streams()
        for other, binding in slots.items():
            stream = resolve(binding, current)
            if other != key and not stream['mute']:
                raise ValueError('Other TV did not mute')
        write(slots[key], 'set-sink-input-mute', 0)


def rotate(slot, ticks):
    key = slot_number(slot)
    if type(ticks) is not int or not -100 <= ticks <= 100:
        raise ValueError('Invalid TV volume ticks')
    if not ticks:
        return
    with locked():
        binding = load()[key]
        state = reading(slot, resolve(binding, streams()))
        volume = max(0, min(100, state['volume'] + ticks * 2))
        write(binding, 'set-sink-input-volume', f'{volume:.3f}%')


def learn(slot, window, timeout=30):
    """Operator unmutes exactly one player; correlate its newly created stream.

    Existing player must first be browser-muted until its old stream disappears.
    This is explicit calibration, never attempted automatically during a press.
    """
    slot_number(slot)
    window_identity(window)
    before = {s['index'] for s in streams()}
    print('Unmute only this YouTube TV player now. Waiting for one new Chrome stream.', flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new = [s for s in streams() if s['index'] not in before and
               s.get('properties', {}).get('application.process.binary') in ('chrome', 'chromium')]
        if len(new) > 1:
            raise ValueError('Multiple new Chrome streams; retry calibration')
        if new:
            bind(slot, new[0]['index'], window)
            return
        time.sleep(.2)
    raise TimeoutError('No new Chrome stream; browser-mute the player and retry')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'bind', 'learn', 'solo', 'rotate'])
    parser.add_argument('--slot', type=int, choices=range(4))
    parser.add_argument('--stream', type=int)
    parser.add_argument('--window', type=lambda s: int(s, 0))
    parser.add_argument('--ticks', type=int, default=0)
    args = parser.parse_args()
    if args.action == 'status':
        print(json.dumps(snapshot(), indent=2))
    elif args.action == 'bind':
        bind(args.slot, args.stream, args.window)
    elif args.action == 'learn':
        learn(args.slot, args.window)
    elif args.action == 'solo':
        solo(args.slot)
    else:
        rotate(args.slot, args.ticks)


if __name__ == '__main__':
    main()
