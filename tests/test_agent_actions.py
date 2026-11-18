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

    def test_compaction_asks_the_owner_and_needs_its_confirmation(self):
        a=self.attention();a.setting_messages={}
        def confirm(sock,message):
            event,result=a.setting_messages[message['requestId']]
            result.update(ok=True);event.set()
        with patch.object(a,'send',side_effect=confirm) as send:
            a.compact_thread('task')
        message=send.call_args.args[1]
        self.assertEqual((message['method'],message['version'],message['targetClientId'],message['params']),
                         ('thread-follower-compact-thread',1,'owner',{'conversationId':'task'}))
        self.assertEqual(a.setting_messages,{})
        with patch.object(a,'send',side_effect=lambda sock,message: a.setting_messages[message['requestId']][0].set()), \
                self.assertRaises(RuntimeError):
            a.compact_thread('task')
        with patch.object(a,'send') as send, self.assertRaises(RuntimeError):
            a.compact_thread('unfollowed')
        send.assert_not_called()

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
