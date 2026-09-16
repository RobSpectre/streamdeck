import unittest
from tools.codex_attention import apply_change, needs_input


class AttentionTests(unittest.TestCase):
    def test_only_pending_input_lights_keys(self):
        self.assertFalse(needs_input({'threadRuntimeStatus': {'type': 'active', 'activeFlags': []}}))
        self.assertFalse(needs_input({'threadRuntimeStatus': {'type': 'idle'}, 'hasUnreadTurn': True}))
        for flag in ['waitingOnApproval', 'waitingOnUserInput']:
            self.assertTrue(needs_input({'threadRuntimeStatus': {'type': 'active', 'activeFlags': [flag]}}))
        self.assertFalse(needs_input({'requests': [{'method': 'item/tool/call'}]}))

    def test_question_lights_and_resolving_dims(self):
        state = apply_change({}, {'type': 'snapshot', 'conversationState': {
            'requests': [], 'turns': ['private content'], 'threadRuntimeStatus': {'type': 'idle'}}})
        self.assertNotIn('turns', state)
        state = apply_change(state, {'type': 'patches', 'patches': [
            {'op': 'add', 'path': ['requests', 0], 'value': {'method': 'item/tool/requestUserInput'}}]})
        self.assertTrue(needs_input(state))
        state = apply_change(state, {'type': 'patches', 'patches': [
            {'op': 'remove', 'path': ['requests', 0]}]})
        self.assertFalse(needs_input(state))

    def test_approval_replacement_and_unrelated_patches(self):
        state = {'requests': [], 'threadRuntimeStatus': {'activeFlags': []}}
        state = apply_change(state, {'type': 'patches', 'patches': [
            {'op': 'replace', 'path': ['requests'], 'value': [{'method': 'item/commandExecution/requestApproval'}]},
            {'op': 'add', 'path': ['turnHistory', 'irrelevant'], 'value': 'ignored'}]})
        self.assertTrue(needs_input(state))
        self.assertNotIn('turnHistory', state)


if __name__ == '__main__':
    unittest.main()
