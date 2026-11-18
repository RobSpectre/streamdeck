"""OpenDeck 2.14.0 + XL touch compatibility; read-only Linux hidraw listener.

That release drops PlusXl TouchScreenPress in elgato.rs. Reports follow
elgato-streamdeck 0.13.1 util::read_lcd_input; observed coordinates are 1200x100.
Forward to OpenDeck so its current-profile lookup and sleep handling still apply.
"""
import fcntl
import os
from pathlib import Path
import select
import subprocess
import threading
import time

DEVICE = 'sd-AD4MA61312Z98B'


def decode(data):
    if len(data) < 10 or data[0] != 1 or data[1] != 2 or data[4] != 1:
        return None  # Ignore key/encoder reports, long holds and swipes.
    x, y = int.from_bytes(data[6:8], 'little'), int.from_bytes(data[8:10], 'little')
    if x >= 1200 or y >= 100:
        return None
    return {'device': DEVICE, 'position': x // 200, 'x': x % 200, 'y': y, 'hold': False}


def find_device(root=Path('/sys/class/hidraw')):
    matches = []
    for path in root.glob('hidraw*/device/uevent'):
        try:
            fields = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
            if fields.get('HID_ID') == '0003:00000FD9:000000C6' and fields.get('HID_UNIQ') == DEVICE[3:]:
                matches.append(Path('/dev')/path.parents[1].name)
        except OSError:
            continue
    if len(matches) != 1:
        raise OSError('Expected exactly one configured + XL')
    return matches[0]


def affected_version():
    try:
        version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'opendeck'],
                                          text=True, timeout=2, stderr=subprocess.DEVNULL).strip()
        return version.split('-')[0] == '2.14.0'
    except (OSError, subprocess.SubprocessError):
        return False


def forwardable(event, visible, now):
    if not 0 <= now - event.get('observed', -100) <= 2:
        return False
    payload = event['payload']
    if payload.get('device') != DEVICE:
        return False
    suffix = f".Encoder.{payload['position']}.0"
    return any(context.startswith(DEVICE+'.') and context.endswith(suffix) and s.get('kind') == 'dial'
               for context, s in visible.items())


class TouchReader:
    def __init__(self, events):
        self.events = events
        self.stop = threading.Event()
        self.thread = None
        if affected_version():
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def run(self):
        # hidraw gives each open file its own input queue; this does not consume
        # OpenDeck's copy. Never send feature reports or write to the device.
        lock = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))/'opendeck-plusxl-touch.lock'
        reported_error = False
        while not self.stop.is_set():
            fd = lock_fd = None
            try:
                lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                path = find_device()
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                print('Plus XL touch compatibility reader connected (OpenDeck 2.14.0)', flush=True)
                reported_error = False
                while not self.stop.is_set():
                    if not select.select([fd], [], [], .5)[0]:
                        continue
                    data = os.read(fd, 512)
                    if not data:
                        raise OSError('Device disconnected')
                    payload = decode(data)
                    if payload:
                        self.events.put({'event': 'plusXLTouch', 'payload': payload, 'observed': time.monotonic()})
            except OSError as error:
                if not reported_error:
                    print(f'Plus XL touch reader unavailable: {type(error).__name__}', flush=True)
                    reported_error = True
            finally:
                for descriptor in (fd, lock_fd):
                    if descriptor is not None:
                        os.close(descriptor)
            self.stop.wait(2)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
