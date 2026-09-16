import threading
import unittest
from unittest.mock import Mock, patch
from tools.codex_attention import CodexAttention
from tools.codex_pedal import dictate

class AgentActionsTests(unittest.TestCase):
    def attention(self):
        a=object.__new__(CodexAttention)
        a.lock=threading.Lock();a.connected=True;a.sock=Mock();a.owners={'task':'owner'}
        a.sent_approvals=set();a.approval_messages={};a.auto_thread=None
        a.states={'task':{'requests':[{'id':42,'method':'item/commandExecution/requestApproval'}]}}
        return a

    def test_scoped_action_is_bound_to_request_and_not_repeated(self):
        a=self.attention()
        with patch.object(a,'send') as send:
            a.extended_action('allow_tool');a.extended_action('allow_tool')
        send.assert_called_once()
        message=send.call_args.args[1]
        self.assertEqual(message['params'],{'conversationId':'task','requestId':42,'decision':'acceptForSession'})
        self.assertEqual(message['targetClientId'],'owner')

    def test_ambiguous_tasks_and_questions_never_autoapprove(self):
        a=self.attention();a.states['other']=a.states['task']
        with patch.object(a,'send') as send:
            a.extended_action('auto');send.assert_not_called()
        self.assertIsNone(a.auto_thread)
        a.states={'task':{'requests':[{'id':42,'method':'item/tool/requestUserInput'}]}}
        self.assertEqual(a.actionable(),[])

    def test_dictation_does_nothing_outside_codex(self):
        with patch('tools.codex_pedal.codex_focused',return_value=None),patch('tools.codex_pedal.subprocess.run') as run:
            dictate();run.assert_not_called()
