import unittest
import threading
from unittest.mock import patch
from tools.agent_telemetry import AgentTelemetry, claude_tokens
from tools.codex_telemetry import context_left


class AgentTelemetryTests(unittest.TestCase):
    def test_context_remaining_uses_current_usage_and_handles_unknown_window(self):
        self.assertEqual(context_left(25000, 100000), '75%')
        self.assertEqual(context_left(120000, 100000), '0%')
        self.assertEqual(context_left(None, 100000), '—')
        self.assertEqual(context_left(100, 0), '—')

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
