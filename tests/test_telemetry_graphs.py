import base64
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from tools.telemetry_graphs import GraphHistory
from tools.codex_telemetry import render


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'history.sqlite'
        self.history = GraphHistory(self.path)

    def tearDown(self):
        self.history.close()
        self.temp.cleanup()

    def test_windows_gaps_and_raw_precision(self):
        self.history.observe('codex', {'session': (1234567, 'a'), 'month': (23456789, None)}, 10000)
        self.assertEqual(self.history.series('codex', 'session', 10000)[-1], 1234567)
        self.assertEqual(self.history.series('codex', 'session', 10010)[-3:], (1234567, None, None))
        self.assertEqual(len(self.history.series('codex', 'session', 10000)), 120)
        self.assertEqual(len(self.history.series('codex', 'month', 10000)), 144)
        self.assertTrue(all(v is None for v in self.history.series('codex', 'session', 10600)))
        self.assertIn(23456789, self.history.series('codex', 'month', 10600))

    def test_task_changes_and_unavailable_are_gaps_not_zero(self):
        self.history.observe('claude', {'session': (5000, 'first')}, 10000)
        self.history.observe('claude', {'session': (100, 'second')}, 10005)
        self.assertEqual(self.history.series('claude', 'session', 10005)[-2:], (None, 100))
        self.history.observe('claude', {'session': (float('nan'), 'second')}, 10010)
        self.assertEqual(self.history.series('claude', 'session', 10010)[-2:], (100, None))

    def test_restart_persistence_is_bounded(self):
        for i in range(130):
            self.history.observe('hermes', {'speed': (i, 'a')}, i*5)
        count = self.history.db.execute("SELECT COUNT(*) FROM samples WHERE metric='speed'").fetchone()[0]
        self.assertEqual(count, 120)
        self.history.close()
        self.history = GraphHistory(self.path)
        self.assertEqual(self.history.series('hermes', 'speed', 645)[-1], 129)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_same_bucket_is_sampled_once(self):
        self.history.observe('codex', {'speed': (5, 'a')}, 10000)
        self.history.observe('codex', {'speed': (99, 'a')}, 10001)
        self.assertEqual(self.history.series('codex', 'speed', 10001)[-1], 5)

    def test_old_speed_semantics_are_invalidated_without_losing_other_history(self):
        self.history.observe('codex', {'speed': (40, 'a'), 'session': (5000, 'a')}, 10000)
        self.history.db.execute('PRAGMA user_version=0')
        self.history.close()
        self.history = GraphHistory(self.path)
        self.assertTrue(all(v is None for v in self.history.series('codex', 'speed', 10000)))
        self.assertEqual(self.history.series('codex', 'session', 10000)[-1], 5000)
        self.history.observe('codex', {'speed': (0, 'a')}, 10005)
        self.history.close()
        self.history = GraphHistory(self.path)
        self.assertEqual(self.history.series('codex', 'speed', 10005)[-1], 0)

    def test_startup_unavailable_sample_can_recover_within_long_bucket(self):
        self.history.observe('codex', {}, 12000)
        self.history.observe('codex', {'month': (1234567, None)}, 12001)
        self.assertEqual(self.history.series('codex', 'month', 12001)[-1], 1234567)
        self.history.close()
        self.history = GraphHistory(self.path)
        self.history.observe('codex', {}, 12002)
        self.assertEqual(self.history.series('codex', 'month', 12002)[-1], 1234567)

    def test_graph_affects_background_without_changing_warning_border(self):
        value = ('CONTEXT LEFT', '9%', 'CURRENT TASK', '#ffffff')
        history = tuple(100-i*90/119 for i in range(120))
        def decode(data):
            return Image.open(io.BytesIO(base64.b64decode(data.split(',')[1])))
        plain = decode(render(value, 0))
        graph = decode(render(value, 0, history))
        self.assertEqual(graph.size, (144, 144))
        self.assertEqual(plain.getpixel((72, 4)), graph.getpixel((72, 4)))
        self.assertNotEqual(plain.getpixel((20, 96)), graph.getpixel((20, 96)))
        self.assertEqual(render(value, 0, history), render(value, 0, history))
