"""Shared, low-frequency presence checks and sleeping collector gates."""
import os
from pathlib import Path
import threading
import time

from tools.cli_agent_bridge import desktop_session


def hermes_cli(process, args):
    """This user's Hermes: the legacy launcher, or its bundled runtime named hermes."""
    home = Path.home()/'.hermes'
    if str(home/'hermes-agent/hermes') in args[:2]:
        return True
    # Current launchers exec Hermes' bundled `python3 -I -c` bootstrap and main()
    # sets comm. The Docker demo's Hermes has the same name and a terminal too;
    # the kernel's executable path, which setproctitle cannot rewrite, keeps it out.
    return (process.joinpath('comm').read_text().strip() == 'hermes'
            and Path(os.readlink(process/'exe')).is_relative_to(home.resolve()))


def detect(proc_root=Path('/proc')):
    present = set()
    for process in proc_root.glob('[0-9]*'):
        try:
            args = process.joinpath('cmdline').read_bytes().decode().split('\0')
            stat = process.joinpath('stat').read_text().rsplit(')', 1)[1].split()
            names = [Path(a).name for a in args[:2]]
            # Desktop work can exist without a local Code worker. Keep app
            # presence separate: it must not wake CLI collectors or grant hooks
            # an interactive owner merely because the desktop is open.
            if (process.joinpath('comm').read_text().strip() == 'claude-desktop'
                    and os.readlink(process/'exe') == '/usr/lib/claude-desktop/claude-desktop'
                    and not any('--type=' in arg for arg in args)):
                present.add('claude_desktop')
            if ('claude' in names or 'claude-code' in names) and (int(stat[4]) or desktop_session(process)):
                present.add('claude')
            if int(stat[4]) and hermes_cli(process, args):
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
