import unittest
import threading
from unittest.mock import patch
from tools.agent_telemetry import AgentTelemetry, claude_tokens
from tools.codex_telemetry import context_left


class AgentTelemetryTests(unittest.TestCase):
    def test_desktop_without_code_worker_is_open_with_unavailable_live_metrics(self):
        from unittest.mock import Mock
        agent = object.__new__(AgentTelemetry)
        agent.lock = threading.Lock()
        agent.presence = Mock()
        agent.presence.is_open.side_effect = lambda name: name == 'claude_desktop'
        agent.data = {'claude': {'model': 'old-model', 'session': 1000, 'month': 2000}}
        samples = {}
        with patch('tools.agent_telemetry.sessions') as sessions, \
                patch('tools.agent_telemetry.pending', return_value=[]):
            values = agent.values('claude', samples)
            sessions.assert_not_called()
        self.assertEqual(values['activity'][1:3], ('OPEN', 'DESKTOP · NO TELEMETRY'))
        self.assertEqual(values['context'][1], '—')
        self.assertEqual(values['quota'][1], 'N/A')
        self.assertEqual(values['session'][2], 'CACHED · LOCAL')
        self.assertTrue(all(value[0] is None for value in samples.values()))

    def test_live_claude_session_takes_precedence_over_desktop_presence(self):
        from unittest.mock import Mock
        agent = object.__new__(AgentTelemetry)
        agent.lock = threading.Lock()
        agent.presence = Mock()
        agent.presence.is_open.return_value = True
        agent.data = {'claude': {}}
        current = {'session': 'a', 'updated': 1, 'active': True, 'model': 'current'}
        with patch('tools.agent_telemetry.sessions', return_value=[current]), \
                patch('tools.agent_telemetry.pending', return_value=[]):
            self.assertEqual(agent.values('claude')['activity'][1:3], ('ACTIVE', 'current'))

    def test_graph_samples_keep_raw_counts_and_context_precision(self):
        agent = object.__new__(AgentTelemetry)
        agent.lock = threading.Lock()
        agent.data = {'hermes': {'session': 1234567, 'month': 23456789, 'session_id': 'a'}}
        current = {'session': 'a', 'updated': 1, 'active': True, 'native_tps': 84.25, 'context_remaining': 18.75}
        samples = {}
        with patch('tools.agent_telemetry.sessions', return_value=[current]), patch('tools.agent_telemetry.pending', return_value=[]):
            values = agent.values('hermes', samples)
        self.assertEqual(values['session'][1], '1.2M')
        self.assertEqual(samples['session'], (1234567, 'a'))
        self.assertEqual(samples['speed'], (84.25, 'a'))
        self.assertEqual(samples['context'], (18.75, 'a'))
        self.assertEqual(samples['month'], (23456789, None))

    def test_idle_cli_graph_is_zero_but_last_average_is_retained(self):
        for name in ('claude', 'hermes'):
            agent = object.__new__(AgentTelemetry)
            agent.lock = threading.Lock()
            agent.data = {name: {'session': 1000, 'month': 2000, 'output': 200, 'session_id': 'a'}}
            agent.speed_samples = {(name, 'a', 980): (990, 100)}
            current = {'session': 'a', 'updated': 1000, 'active': False, 'native_tps': 84.25,
                       'turn_started': 980, 'turn_ended': 1000}
            samples = {}
            with patch('tools.agent_telemetry.sessions', return_value=[current]), \
                    patch('tools.agent_telemetry.pending', return_value=[]), \
                    patch('tools.agent_telemetry.time.time', return_value=1000):
                values = agent.values(name, samples)
                self.assertEqual(samples['speed'], (0, 'a'))
                self.assertGreater(float(values['speed'][1]), 0)
                current['active'] = True
                agent.values(name, samples)
                self.assertGreater(samples['speed'][0], 0)
                del current['active']
                agent.values(name, samples)
                self.assertIsNone(samples['speed'][0])

    def test_context_remaining_uses_current_usage_and_handles_unknown_window(self):
        self.assertEqual(context_left(25000, 100000), '75%')
        self.assertEqual(context_left(120000, 100000), '0%')
        self.assertEqual(context_left(None, 100000), '—')
        self.assertEqual(context_left(100, 0), '—')

    def test_claude_model_uses_claudes_own_name_only_for_the_model_in_use(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            transcript = Path(folder)/'.claude/projects/p/s.jsonl'
            transcript.parent.mkdir(parents=True)
            lines = [{'type': 'attachment', 'sessionId': 's', 'timestamp': '2026-09-27T20:00:00Z',
                      'attachment': {'type': 'model', 'identity': {'modelId': 'claude-opus-5-5', 'marketingName': 'Opus 5.5'}}},
                     {'type': 'assistant', 'sessionId': 's', 'timestamp': '2026-09-27T20:00:01Z', 'uuid': 'u1',
                      'message': {'id': 'm1', 'model': 'claude-opus-5-5', 'usage': {'input_tokens': 1, 'output_tokens': 2}}}]
            transcript.write_text(''.join(json.dumps(l)+'\n' for l in lines))
            agent = object.__new__(AgentTelemetry)
            agent.files = {}
            with patch('tools.agent_telemetry.Path.home', return_value=Path(folder)), \
                    patch('tools.agent_telemetry.sessions', return_value=[]):
                self.assertEqual(agent.claude(0)['model'], 'Opus 5.5')
                # After a /model switch the name no longer describes the replies.
                lines[1]['message'].update(id='m2', model='claude-sonnet-5')
                with transcript.open('a') as stream:
                    stream.write(json.dumps({**lines[1], 'timestamp': '2026-09-27T20:00:02Z'})+'\n')
                self.assertEqual(agent.claude(0)['model'], 'claude-sonnet-5')

    def test_claude_cache_is_separate_input(self):
        self.assertEqual(claude_tokens({'input_tokens': 10, 'output_tokens': 20,
            'cache_creation_input_tokens': 30, 'cache_read_input_tokens': 40}), 100)

    def test_unlinked_metrics_are_not_fabricated(self):
        agent = object.__new__(AgentTelemetry)
        agent.lock = threading.Lock()
        agent.data = {'hermes': {'session': 100, 'month': 200, 'month_lower_bound': True}}
        with patch('tools.agent_telemetry.sessions', return_value=[]), patch('tools.agent_telemetry.hermes_cli_open', return_value=False):
            values = agent.values('hermes')
        self.assertEqual(values['activity'][1], 'OFFLINE')
        self.assertEqual(values['quota'][1], 'N/A')
        self.assertEqual(values['month'][1], '≥200')

    def test_running_cli_without_hooks_is_open_not_offline(self):
        agent = object.__new__(AgentTelemetry)
        agent.lock = threading.Lock()
        agent.data = {'hermes': {}}
        with patch('tools.agent_telemetry.sessions', return_value=[]), patch('tools.agent_telemetry.pending', return_value=[]), patch('tools.agent_telemetry.hermes_cli_open', return_value=True):
            values = agent.values('hermes')
        self.assertEqual(values['activity'][1], 'OPEN')
        self.assertEqual(values['activity'][2], 'Model unknown')
