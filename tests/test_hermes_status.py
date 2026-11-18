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
    def test_native_context_without_cli_api_hooks(self):
        compressor = SimpleNamespace(last_prompt_tokens=24000, context_length=256000)
        cli = SimpleNamespace(agent=SimpleNamespace(context_compressor=compressor))
        self.assertEqual(plugin.ui_context(cli), {'context_used': 24000, 'context_limit': 256000})
        compressor.context_length = 128000  # Native model switch / explicit window.
        self.assertEqual(plugin.ui_context(cli)['context_limit'], 128000)
        for used, limit in [(-1, 128000), (float('nan'), 128000), (24000, 0), (24000, '256000'),
                            (True, 128000), (24000, float('inf'))]:
            compressor.last_prompt_tokens, compressor.context_length = used, limit
            self.assertIn(None, plugin.ui_context(cli).values())
        cli.agent = None
        self.assertEqual(plugin.ui_context(cli), {'context_used': None, 'context_limit': None})

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
        cli.agent.context_compressor=SimpleNamespace(last_prompt_tokens=24000,context_length=256000)
        with tempfile.TemporaryDirectory() as folder,patch.object(plugin.bridge,'CACHE',Path(folder)),patch.object(bridge,'CACHE',Path(folder)),patch.object(plugin.gc,'get_objects',return_value=[cli]),patch.object(plugin.time,'sleep',side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):plugin.monitor_cli()
            saved=bridge.sessions('hermes')[0]
            self.assertEqual(saved['pid'],os.getpid())
            self.assertEqual(saved['native_tps'],19)
            self.assertEqual((saved['context_used'],saved['context_limit']),(24000,256000))
            agent=object.__new__(AgentTelemetry);agent.lock=threading.Lock();agent.data={'hermes':{}}
            self.assertEqual(agent.values('hermes')['speed'][1],'19')
            self.assertEqual(agent.values('hermes')['context'][1],'91%')

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

class HermesApprovalTests(unittest.TestCase):
    def test_native_permission_is_private_scoped_and_once_only(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder, patch.object(plugin.bridge,'CACHE',Path(folder)), patch.object(bridge,'CACHE',Path(folder)):
            callbacks=[]
            state={'command':'private command','description':'private reason',
                   'choices':['once','session','always','deny'], 'selected':2,
                   'response_queue':object()}
            app=SimpleNamespace(loop=SimpleNamespace(call_soon_threadsafe=callbacks.append))
            cli=SimpleNamespace(_approval_state=state,_app=app,
                                _approval_deadline=plugin.time.monotonic()+60,
                                _handle_approval_selection=Mock())
            monitor=plugin.ApprovalMonitor();monitor.tick(cli)
            marker=bridge.pending()[0]
            self.assertEqual(marker['kind'],'native_approval')
            self.assertNotIn('private',str(marker))
            self.assertFalse(marker['extended'])
            self.assertFalse(bridge.respond_question('auto'))
            self.assertFalse(bridge.respond_question('allow_tool'))
            bridge.respond_question('approve');monitor.tick(cli)
            callbacks.pop()()
            self.assertEqual(state['selected'],0)
            cli._handle_approval_selection.assert_called_once()
            cli._handle_approval_selection.reset_mock()
            monitor.tick(cli);bridge.respond_question('deny');monitor.tick(cli)
            callbacks.pop()()
            self.assertEqual(state['selected'],3)
            cli._handle_approval_selection.assert_called_once()
            cli._approval_state=None;monitor.tick(cli)
            self.assertEqual(bridge.pending(),[])

    def test_changed_or_expired_permission_rejects_queued_response(self):
        from unittest.mock import Mock
        for change in ('selection','command','replacement','expiry'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder, patch.object(plugin.bridge,'CACHE',Path(folder)), patch.object(bridge,'CACHE',Path(folder)):
                callbacks=[]
                state={'command':'test','choices':['once','deny'],'selected':0}
                cli=SimpleNamespace(_approval_state=state,
                    _app=SimpleNamespace(loop=SimpleNamespace(call_soon_threadsafe=callbacks.append)),
                    _approval_deadline=plugin.time.monotonic()+60,_handle_approval_selection=Mock())
                monitor=plugin.ApprovalMonitor();monitor.tick(cli)
                bridge.respond_question('approve');monitor.tick(cli)
                if change=='selection': state['selected']=1
                elif change=='command': state['command']='changed'
                elif change=='replacement': cli._approval_state=dict(state)
                else: cli._approval_deadline=plugin.time.monotonic()-1
                callbacks.pop()()
                cli._handle_approval_selection.assert_not_called()
                monitor.tick(cli)
                if change=='expiry': self.assertEqual(bridge.pending(),[])

    def test_native_permission_ambiguity_and_zenity_exclusion(self):
        marker={'kind':'native_approval','request':'test','pid':123}
        with patch.object(bridge,'pending',return_value=[marker,marker]):
            self.assertFalse(bridge.respond_question('approve'))
        with patch.object(bridge,'pending',return_value=[marker]):
            self.assertFalse(bridge.respond_focused('approve','456','_NET_WM_PID = 123'))
