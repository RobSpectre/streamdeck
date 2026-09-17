"""Shared, low-frequency presence checks and sleeping collector gates."""
from pathlib import Path
import threading
import time


def detect(proc_root=Path('/proc')):
    present = set()
    for process in proc_root.glob('[0-9]*'):
        try:
            args = process.joinpath('cmdline').read_bytes().decode().split('\0')
            stat = process.joinpath('stat').read_text().rsplit(')', 1)[1].split()
            names = [Path(a).name for a in args[:2]]
            if int(stat[4]) and ('claude' in names or 'claude-code' in names):
                present.add('claude')
            if int(stat[4]) and str(Path.home()/'.hermes/hermes-agent/hermes') in args[:2]:
                present.add('hermes')
        except (OSError, ValueError, IndexError, UnicodeError):
            continue
    # Connecting here would create another IPC client; the attention reader owns it.
    try:
        socket_path = str(Path.home()/'.codex/ipc/ipc.sock')
        for line in (proc_root/'net/unix').read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 8 and fields[7] == socket_path and fields[3] == '00010000':
                present.add('codex')
    except OSError:
        pass
    return present


class Presence:
    def __init__(self):
        self.condition = threading.Condition()
        self.present = set()
        self.visible = set()
        self.closed = False
        threading.Thread(target=self.run, daemon=True, name='agent-presence').start()

    def run(self):
        while True:
            found = detect()
            with self.condition:
                if self.closed:
                    return
                self.present = found
                self.condition.notify_all()
                if self.condition.wait_for(lambda: self.closed, timeout=5):
                    return

    def show(self, agents):
        with self.condition:
            self.visible = set(agents)
            self.condition.notify_all()

    def is_open(self, agent):
        with self.condition:
            return agent in self.present

    def wait(self, agent, delay=0, visible=True):
        """Wait without polling; reopening/showing a collector refreshes immediately."""
        deadline = time.monotonic()+delay
        with self.condition:
            while not self.closed:
                enabled = agent in self.present and (not visible or agent in self.visible)
                if not enabled:
                    deadline = 0
                    self.condition.wait()
                else:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        return True
                    self.condition.wait(remaining)
            return False

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
