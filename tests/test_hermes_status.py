import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tempfile
from tools import cli_agent_bridge as bridge

spec=importlib.util.spec_from_file_location('hermes_opendeck',Path(__file__).resolve().parents[1]/'integrations/hermes-opendeck/__init__.py')
plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)

class HermesStatusTests(unittest.TestCase):
    def test_throughput_matches_sum_over_sum_not_mean_of_rates(self):
        cli=SimpleNamespace(agent=SimpleNamespace(_api_latency_history=[1,9], _api_output_history=[100,90]))
        self.assertEqual(plugin.ui_throughput(cli),19)
        cli.agent._api_latency_history=[999,1,9]
        self.assertEqual(plugin.ui_throughput(cli),19)
        cli.agent._api_latency_history=[]
        self.assertIsNone(plugin.ui_throughput(cli))
        cli.agent._api_latency_history=[0,0]
        self.assertIsNone(plugin.ui_throughput(cli))

    def test_ui_idle_wins_over_stale_hook_after_interruption(self):
        cli=SimpleNamespace(agent=SimpleNamespace(session_id='a'),_agent_running=True)
        self.assertEqual(plugin.ui_snapshot(cli),('a',True))
        cli._agent_running=False
        self.assertEqual(plugin.ui_snapshot(cli),('a',False))
        with tempfile.TemporaryDirectory() as folder,patch.object(bridge,'CACHE',Path(folder)),patch.object(bridge,'alive',return_value=True):
            bridge.publish('hermes','a','start',pid=123)
            bridge.publish('hermes','a','heartbeat',pid=123,ui_active=False,ui_updated=bridge.time.time())
            self.assertFalse(bridge.sessions('hermes')[0]['active'])

    def test_new_session_does_not_inherit_old_active_indicator(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(bridge,'CACHE',Path(folder)),patch.object(bridge,'alive',return_value=True):
            bridge.publish('hermes','old','start',pid=123)
            bridge.publish('hermes','new','stop',pid=123)
            values=bridge.sessions('hermes')
            self.assertEqual(len(values),1)
            self.assertEqual(values[0]['session'],'new')
            self.assertFalse(values[0]['active'])

    def test_monitor_publishes_native_throughput_for_display(self):
        import os
        import json
        import threading
        from tools.agent_telemetry import AgentTelemetry
        cli_type=type('HermesCLI',(),{'__module__':'cli'})
        cli=cli_type();cli._agent_running=False
        cli.agent=SimpleNamespace(session_id='smoke',model='test-model',_api_latency_history=[1,9],_api_output_history=[100,90])
        with tempfile.TemporaryDirectory() as folder,patch.object(plugin.bridge,'CACHE',Path(folder)),patch.object(bridge,'CACHE',Path(folder)),patch.object(plugin.gc,'get_objects',return_value=[cli]),patch.object(plugin.time,'sleep',side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):plugin.monitor_cli()
            saved=bridge.sessions('hermes')[0]
            self.assertEqual(saved['pid'],os.getpid())
            self.assertEqual(saved['native_tps'],19)
            agent=object.__new__(AgentTelemetry);agent.lock=threading.Lock();agent.data={'hermes':{}}
            self.assertEqual(agent.values('hermes')['speed'][1],'19')

class HermesQuestionTests(unittest.TestCase):
    def test_question_lifecycle_response_and_stale_selection(self):
        import queue
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder, patch.object(plugin.bridge,'CACHE',Path(folder)), patch.object(bridge,'CACHE',Path(folder)):
            callbacks=[]
            state={'question':'Choose', 'choices':['A','B'], 'selected':0, 'response_queue':queue.Queue()}
            app=SimpleNamespace(loop=SimpleNamespace(call_soon_threadsafe=callbacks.append),current_buffer=SimpleNamespace(text=''),invalidate=Mock())
            cli=SimpleNamespace(_clarify_state=state,_app=app,_clarify_freetext=False,_tui_enter_clarify_choice=Mock(),_clarify_teardown=Mock())
            monitor=plugin.QuestionMonitor();monitor.tick(cli)
            self.assertEqual(bridge.pending()[0]['kind'],'question')
            self.assertFalse(bridge.respond_question('auto'))
            self.assertTrue(bridge.respond_question('approve'))
            monitor.tick(cli)
            state['selected']=1
            callbacks.pop()()
            cli._tui_enter_clarify_choice.assert_not_called()
            monitor.tick(cli);bridge.respond_question('approve');monitor.tick(cli)
            callbacks.pop()()
            cli._tui_enter_clarify_choice.assert_called_once()
            monitor.tick(cli);bridge.respond_question('deny');monitor.tick(cli)
            callbacks.pop()()
            self.assertIn('cancelled',state['response_queue'].get_nowait())
            cli._clarify_teardown.assert_called_once()
            cli._clarify_state=None;monitor.tick(cli)
            self.assertEqual(bridge.pending(),[])

    def test_multiple_questions_are_ambiguous(self):
        with patch.object(bridge,'pending',return_value=[{'kind':'question'},{'kind':'question'}]):
            self.assertFalse(bridge.respond_question('approve'))
