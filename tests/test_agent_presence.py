import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.agent_presence import Presence, detect
from tools.codex_telemetry import Telemetry
from tools.agent_telemetry import AgentTelemetry


class PresenceTests(unittest.TestCase):
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
