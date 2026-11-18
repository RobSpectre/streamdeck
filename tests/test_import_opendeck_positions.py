import copy
import unittest
from tools.import_opendeck_positions import adopt


def button(identity, command):
    return {'label_id': identity, 'states': {'0': {'command': command, 'text': identity}}}


def key(identity):
    return {'settings': {'_label_id': identity}, 'states': [{'text': 'LIVE VALUE', 'image': 'data:runtime'}]}


class ImportPositionsTests(unittest.TestCase):
    def setUp(self):
        self.layout = {'devices': {'device': {'page': 0, 'page_names': {'0': 'First', '1': 'Second'},
            'dials': {'0': {'0': {'control': 'spotify'}}},
            'buttons': {'0': {'0': button('a', 'first'), '1': button('b', 'second')},
                        '1': {'0': button('c', 'third'), '1': {'states': {'0': {}}}}}}}}

    def test_cross_page_moves_keep_actions_and_ignore_runtime_images(self):
        profiles = {('device', '0'): {'keys': [key('c'), key('a')]},
                    ('device', '1'): {'keys': [None, key('b')]}}
        original = copy.deepcopy(self.layout)
        result = adopt(self.layout, profiles)['devices']['device']
        self.assertEqual(result['buttons']['0']['0'], button('c', 'third'))
        self.assertEqual(result['buttons']['0']['1'], button('a', 'first'))
        self.assertEqual(result['buttons']['1']['1'], button('b', 'second'))
        self.assertEqual(result['buttons']['1']['0'], {'states': {'0': {}}})
        self.assertEqual(result['dials'], original['devices']['device']['dials'])
        self.assertEqual(self.layout, original)

    def test_unknown_identity_and_wrong_size_refuse_import(self):
        profiles = {('device', '0'): {'keys': [key('unknown'), None]},
                    ('device', '1'): {'keys': [key('c'), None]}}
        with self.assertRaisesRegex(ValueError, 'Unknown key'):
            adopt(self.layout, profiles)
        profiles[('device', '0')]['keys'] = [key('a')]
        with self.assertRaisesRegex(ValueError, 'Unexpected key count'):
            adopt(self.layout, profiles)

    def test_unchanged_page_is_preserved_verbatim(self):
        profiles = {('device', '0'): {'keys': [key('a'), key('b')]},
                    ('device', '1'): {'keys': [key('c'), None]}}
        self.assertEqual(adopt(self.layout, profiles), self.layout)

    def test_removed_key_and_duplicate_shared_identity(self):
        self.layout['devices']['device']['buttons']['1']['0'] = button('a', 'first')
        profiles = {('device', '0'): {'keys': [None, key('b')]},
                    ('device', '1'): {'keys': [key('a'), None]}}
        result = adopt(self.layout, profiles)
        self.assertEqual(result['devices']['device']['buttons']['0']['0'], {'states': {'0': {}}})
        self.layout['devices']['device']['buttons']['1']['0'] = button('a', 'different')
        with self.assertRaisesRegex(ValueError, 'Ambiguous source identity'):
            adopt(self.layout, profiles)
