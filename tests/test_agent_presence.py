import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.agent_presence import Presence, detect
from tools.codex_telemetry import Telemetry
from tools.agent_telemetry import AgentTelemetry, hermes_cli_open


def fake_process(root, pid, args, comm, exe, tty=34818, ppid=1):
    path = root/str(pid)
    path.mkdir()
    path.joinpath('cmdline').write_bytes('\0'.join(args+['']).encode())
    path.joinpath('stat').write_text(f'{pid} ({comm}) S {ppid} {pid} {pid} {tty} {pid}')
    path.joinpath('comm').write_text(comm+'\n')
    path.joinpath('exe').symlink_to(exe)


class PresenceTests(unittest.TestCase):
    def test_desktop_presence_does_not_imply_a_local_code_worker(self):
        desktop = '/usr/lib/claude-desktop/claude-desktop'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_process(root, 10, ['/tmp/claude-desktop'], 'claude-desktop', '/tmp/claude-desktop', tty=0)
            fake_process(root, 11, [desktop, '--type=renderer'], 'claude-desktop', desktop, tty=0)
            fake_process(root, 12, [desktop+' --type=utility'], 'claude-desktop', desktop, tty=0)
            self.assertNotIn('claude_desktop', detect(root))
            fake_process(root, 13, [desktop], 'claude-desktop', desktop, tty=0)
            self.assertIn('claude_desktop', detect(root))
            self.assertNotIn('claude', detect(root))

    def test_sleep_wake_hide_and_shutdown(self):
        with patch('tools.agent_presence.detect', return_value=set()):
            presence = Presence()
            completed = threading.Event()
            worker = threading.Thread(target=lambda: (presence.wait('hermes'), completed.set()))
            worker.start()
            self.assertFalse(completed.wait(.03))
            with presence.condition:
                presence.present = {'hermes'}
                presence.condition.notify_all()
            self.assertFalse(completed.wait(.03))
            presence.show({'hermes'})
            self.assertTrue(completed.wait(1))
            worker.join(1)
            presence.show(set())
            presence.close()
            self.assertFalse(presence.wait('hermes'))

    def test_showing_paused_collector_skips_long_refresh_delay(self):
        with patch('tools.agent_presence.detect', return_value={'codex'}):
            presence = Presence()
            completed = threading.Event()
            # It starts hidden; a quota worker must not retain its 60s deadline.
            entered = threading.Event()
            def collect():
                entered.set()
                if presence.wait('codex', 60):
                    completed.set()
            worker = threading.Thread(target=collect)
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(completed.wait(.03))
            presence.show({'codex'})
            self.assertTrue(completed.wait(1))
            presence.close()
            worker.join(1)

    def test_closed_gate_never_reads_history_or_starts_quota_helper(self):
        from unittest.mock import Mock
        gate = Mock()
        gate.wait.return_value = False
        codex = object.__new__(Telemetry)
        codex.presence = gate
        agents = object.__new__(AgentTelemetry)
        agents.presence = gate
        with patch('tools.codex_telemetry.sqlite3.connect') as db, \
                patch('tools.codex_telemetry.read_quota') as quota, \
                patch.object(agents, 'hermes') as hermes, patch.object(agents, 'claude') as claude:
            codex.scan()
            codex.poll_quota()
            agents.scan('hermes')
            agents.scan('claude')
            for reader in (db, quota, hermes, claude):
                reader.assert_not_called()

    def test_codex_requires_listening_socket_not_stale_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'net').mkdir()
            path = str(Path.home()/'.codex/ipc/ipc.sock')
            (root/'net/unix').write_text('header\n0: 2 0 00000000 0001 01 123 '+path+'\n')
            self.assertNotIn('codex', detect(root))
            (root/'net/unix').write_text('header\n0: 2 0 00010000 0001 01 123 '+path+'\n')
            self.assertIn('codex', detect(root))

    def test_hermes_bundled_runtime_counts_only_from_this_home(self):
        runtime = 'tools/python-3.14.7+20260901-linux-x64/bin/'
        exe = str((Path.home()/'.hermes').resolve()/runtime/'python3.14')
        bootstrap = [str(Path.home()/'.hermes'/runtime/'python3'), '-I', '-c', 'from hermes_cli.main import main']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_process(root, 10, bootstrap+['gateway', 'run'], 'hermes', exe, tty=0)
            # The Docker demo is also named hermes and runs on a terminal.
            fake_process(root, 11, ['/home/demo/.hermes/'+runtime+'python3', '-I', '-c', 'demo'], 'hermes',
                         '/home/demo/.hermes/'+runtime+'python3.14')
            fake_process(root, 12, bootstrap[:2]+['-m', 'helper'], 'python3', exe)
            self.assertNotIn('hermes', detect(root))
            self.assertFalse(hermes_cli_open(root))
            fake_process(root, 13, bootstrap, 'hermes', exe)
            self.assertIn('hermes', detect(root))
            self.assertTrue(hermes_cli_open(root))

    def test_claude_desktop_session_counts_without_a_terminal(self):
        home = Path.home().resolve()
        app = str(home/'.config/Claude/claude-code/2.1.280/claude')
        sdk = str(home/'project/.venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_process(root, 30, ['/usr/lib/claude-desktop/claude-desktop'], 'claude-desktop',
                         '/usr/lib/claude-desktop/claude-desktop', tty=0)
            fake_process(root, 32, ['python3', 'agent.py'], 'python3', '/usr/bin/python3.12', tty=0)
            # Agent SDK apps and `claude -p` scripts also run it without a terminal.
            fake_process(root, 33, [sdk, '--output-format', 'stream-json'], 'claude', sdk, tty=0, ppid=32)
            self.assertNotIn('claude', detect(root))
            fake_process(root, 31, [app, '--output-format', 'stream-json'], 'claude', app, tty=0, ppid=30)
            self.assertIn('claude', detect(root))

    def test_claude_desktop_bundled_disclaimer_requires_verified_parent_chain(self):
        from tools.cli_agent_bridge import interactive_owner
        app = str(Path.home().resolve()/'.config/Claude/claude-code/2.1.308/hash/claude')
        desktop = '/usr/lib/claude-desktop/claude-desktop'
        helper = '/usr/lib/claude-desktop/resources/disclaimer'
        cases = [
            (helper, desktop, 'claude-desktop', app, True),
            ('/tmp/disclaimer', desktop, 'claude-desktop', app, False),
            (helper, '/tmp/claude-desktop', 'claude-desktop', app, False),
            (helper, '/usr/bin/python3', 'python3', app, False),
            (helper, desktop, 'claude-desktop', '/tmp/sdk/claude', False),
        ]
        for helper_exe, owner_exe, owner_comm, cli_exe, expected in cases:
            with self.subTest(helper=helper_exe, owner=owner_exe, cli=cli_exe), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                fake_process(root, 30, [owner_exe], owner_comm, owner_exe, tty=0)
                fake_process(root, 31, [helper_exe], 'disclaimer', helper_exe, tty=0, ppid=30)
                fake_process(root, 32, [cli_exe], 'claude', cli_exe, tty=0, ppid=31)
                self.assertEqual('claude' in detect(root), expected)
                self.assertEqual(interactive_owner(32, root), expected)
                # An exiting helper must fail closed for both consumers.
                (root/'31/exe').unlink()
                self.assertNotIn('claude', detect(root))
                self.assertFalse(interactive_owner(32, root))

    def test_legacy_hermes_launcher_still_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_process(root, 20, ['/usr/bin/python3', str(Path.home()/'.hermes/hermes-agent/hermes')],
                         'python3', '/usr/bin/python3.12')
            self.assertIn('hermes', detect(root))

    def test_closed_agents_override_cached_idle_sessions_at_boot(self):
        from unittest.mock import Mock
        gate = Mock()
        gate.is_open.return_value = False
        codex = object.__new__(Telemetry)
        codex.presence = gate
        codex.attention = Mock()
        codex.attention.snapshot.return_value = (True, {'old': {'threadRuntimeStatus': {'type': 'idle'}}})
        codex.lock = threading.Lock()
        codex.monthly = None
        codex.thread_stats = {}
        agents = object.__new__(AgentTelemetry)
        agents.presence = gate
        agents.lock = threading.Lock()
        agents.data = {'claude': {}, 'hermes': {}}
        with patch('tools.agent_telemetry.sessions', return_value=[{'updated': 1, 'active': False}]) as sessions, \
                patch('tools.agent_telemetry.pending', return_value=[]):
            self.assertEqual(codex.values()['activity'][1], 'OFFLINE')
            for name in ('claude', 'hermes'):
                self.assertEqual(agents.values(name)['activity'][1], 'OFFLINE')
            sessions.assert_not_called()
