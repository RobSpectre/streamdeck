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

    def test_desktop_app_session_is_interactive_without_a_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'31').mkdir()
            (root/'31/stat').write_text('31 (claude) S 30 31 31 0 31')
            with patch.object(bridge, 'desktop_session', return_value=False):
                self.assertFalse(bridge.interactive_owner(31, root))
            with patch.object(bridge, 'desktop_session', return_value=True) as desktop:
                self.assertTrue(bridge.interactive_owner(31, root))
            desktop.assert_called_once_with(root/'31')
            with patch.object(bridge, 'desktop_session', side_effect=PermissionError):
                self.assertFalse(bridge.interactive_owner(31, root))

    def test_measured_figures_fill_sessions_without_a_statusline(self):
        import json
        session='0f8fad5b-d9cb-469f-a165-70867728950e'
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge,'CACHE',Path(folder)), \
                patch.object(bridge,'alive',return_value=True):
            root=Path(folder)
            (root/'claude').mkdir();(root/'claude-measure').mkdir()
            (root/'claude/s.json').write_text(json.dumps({'session':session,'pid':1,'updated':1}))
            figures={'session':session,'measured':100.0,'context':{'tokens':50000,'window':200000,'percent':25},
                     'rateLimits':[{'kind':'five_hour','percentUsed':12.5,'resetsAt':'2026-09-28T01:00:00Z'},{'kind':'bad'}]}
            (root/'claude-measure'/(session+'.json')).write_text(json.dumps(figures))
            value=bridge.sessions('claude')[0]
            self.assertEqual((value['context_remaining'],value['quota_updated']),(75.0,100.0))
            self.assertEqual(value['rate_limits'],{'five_hour':{'used_percentage':12.5,'resets_at':1790557200.0}})
            # A fresher statusline reading wins over an older measurement.
            (root/'claude/s.json').write_text(json.dumps({'session':session,'pid':1,'updated':1,'quota_updated':200,'context_remaining':40}))
            self.assertEqual(bridge.sessions('claude')[0]['context_remaining'],40)
            # A session id that is not a UUID never becomes a path.
            (root/'claude/s.json').write_text(json.dumps({'session':'../x','pid':1,'updated':1}))
            self.assertNotIn('context_remaining',bridge.sessions('claude')[0])

    def test_hook_effort_is_recorded_and_never_blanked(self):
        with patch.object(bridge,'interactive_owner',return_value=True), patch.object(bridge,'publish') as publish:
            bridge.claude_hook({'hook_event_name':'Stop','session_id':'s','effort':{'level':'max'}},'hook')
            self.assertEqual(publish.call_args.kwargs['effort'],'max')
            bridge.claude_hook({'hook_event_name':'SessionStart','session_id':'s'},'hook')
            self.assertNotIn('effort',publish.call_args.kwargs)

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
