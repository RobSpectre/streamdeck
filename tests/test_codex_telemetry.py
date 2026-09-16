import json
from pathlib import Path
import tempfile
import unittest
from tools.codex_telemetry import RolloutUsage, compact, quota_window, render


class TelemetryTests(unittest.TestCase):
    def test_quota_uses_limiting_window_and_reset_age(self):
        limits = {'rateLimitsByLimitId': {'codex': {
            'primary': {'usedPercent': 80, 'windowDurationMins': 300, 'resetsAt': 11000},
            'secondary': {'usedPercent': 25, 'windowDurationMins': 10080, 'resetsAt': 604800}}}}
        remaining, age, duration = quota_window(limits, 8640)
        self.assertEqual(remaining, 20)
        self.assertAlmostEqual(age, .1)
        self.assertEqual(duration, 300)
        self.assertEqual(quota_window({}, 100), (None, None, None))

    def test_usage_is_incremental_and_deduplicates_counters(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'rollout.jsonl'
            def line(total, output, stamp='2026-09-16T16:00:00Z'):
                return json.dumps({'timestamp': stamp, 'type': 'event_msg', 'payload': {
                    'type': 'token_count', 'info': {
                        'total_token_usage': {'total_tokens': total, 'output_tokens': output},
                        'last_token_usage': {'total_tokens': 100, 'output_tokens': 10}}}})+'\n'
            path.write_text(line(1000, 100)+line(1000, 100)+line(1150, 120))
            usage = RolloutUsage(path, 0)
            usage.update()
            self.assertEqual(sum(n for _, n in usage.events), 250)
            usage.update()
            self.assertEqual(sum(n for _, n in usage.events), 250)
            with path.open('a') as f:
                f.write(line(1200, 130))
            usage.update()
            self.assertEqual(sum(n for _, n in usage.events), 300)

    def test_compact_and_render(self):
        self.assertEqual(compact(1250000), '1.2M')
        self.assertEqual(compact(None), '—')
        self.assertTrue(render(('QUOTA LEFT', '96%', 'WEEKLY', '#41d98b')).startswith('data:image/png;base64,'))


if __name__ == '__main__':
    unittest.main()
