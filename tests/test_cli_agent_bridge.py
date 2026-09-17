import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from tools import cli_agent_bridge as bridge


class BridgeTests(unittest.TestCase):
    def test_claude_returns_only_one_request_decision(self):
        payload = {'session_id':'test', 'hook_event_name':'PermissionRequest', 'tool_name':'Bash', 'tool_input':{'command':'test'}}
        for decision, expected in [('approve','allow'),('deny','deny')]:
            with patch.object(bridge,'interactive_owner',return_value=True), patch.object(bridge,'publish'), \
                    patch.object(bridge,'approval_dialog',return_value=decision):
                output = bridge.claude_hook(payload,'hook')['hookSpecificOutput']['decision']
                self.assertEqual(output,{'behavior':expected})

    def test_noninteractive_claude_keeps_native_policy(self):
        with patch.object(bridge,'interactive_owner',return_value=False), patch.object(bridge,'approval_dialog') as dialog:
            self.assertEqual(bridge.claude_hook({'hook_event_name':'PermissionRequest'},'hook'),{})
            dialog.assert_not_called()

    def test_only_exact_focused_request_gets_a_decision(self):
        request = {'request':'abc', 'pid':123, 'title':'Hermes CLI approval · abc'}
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge,'CACHE',Path(folder)), \
                patch.object(bridge,'pending',return_value=[request]), \
                patch.object(bridge.subprocess,'check_output',return_value='456'):
            self.assertFalse(bridge.respond_focused('approve','456','_NET_WM_PID = 1234\nHermes CLI approval · abc'))
            self.assertFalse(bridge.respond_focused('approve','789','_NET_WM_PID = 123\nHermes CLI approval · abc'))
            self.assertTrue(bridge.respond_focused('approve','456','_NET_WM_PID = 123\nHermes CLI approval · abc'))
            self.assertEqual(bridge.read(Path(folder)/'decisions/abc.json'),{'request':'abc','decision':'approve'})

    def test_pending_uses_live_owner_but_focus_uses_dialog_pid(self):
        request = {'request': 'abc', 'pid': 456, 'dialog_pid': 456, 'owner_pid': 123,
                   'title': 'Hermes CLI approval · abc', 'expires': bridge.time.time()+30}
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge, 'CACHE', Path(folder)), \
                patch.object(bridge, 'alive', side_effect=lambda pid: pid == 123), \
                patch.object(bridge.subprocess, 'check_output', return_value='789'):
            bridge.atomic(Path(folder)/'pending/abc.json', request)
            self.assertEqual(bridge.pending(), [request])
            with patch.object(bridge, 'alive', side_effect=lambda pid: pid in (123, 456)):
                self.assertTrue(bridge.respond_focused(
                    'approve', '789', '_NET_WM_PID = 456\nHermes CLI approval · abc'))

    def test_idle_and_dead_processes_do_not_claim_attention(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge,'CACHE',Path(folder)):
            bridge.publish('claude','session','start',pid=999999999)
            self.assertEqual(bridge.sessions('claude'),[])
            self.assertEqual(bridge.pending(),[])

    def test_auto_grant_is_limited_to_its_live_owner_and_session(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge,'CACHE',Path(folder)), patch.object(bridge,'alive',return_value=True):
            bridge.atomic(Path(folder)/'auto.json',{'agent':'claude','session':'one','owner':123})
            self.assertEqual(bridge.approval_dialog('claude','test',session='one',owner=123),'approve')
            with patch.dict(bridge.os.environ,{},clear=True):
                with self.assertRaises(RuntimeError):
                    bridge.approval_dialog('claude','test',session='two',owner=123)
            bridge.disable_auto()
            self.assertEqual(bridge.auto_enabled(),{})
