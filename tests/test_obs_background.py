import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('background', Path(__file__).resolve().parents[1]/'control_obs_background.py')
bg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bg)

class FakeOBS:
    def __init__(self):
        self.sources = [{'sourceName': name, 'sceneItemId': i+10, 'sceneItemEnabled': i==0} for i,name in enumerate(['Space Highway', "'Merica", 'Mars'])]
        self.calls = []
    def get_scene_collection_list(self):
        return SimpleNamespace(current_scene_collection_name='hack.party')
    def get_scene_item_list(self, scene):
        assert scene == 'Loops'
        return SimpleNamespace(scene_items=copy.deepcopy(self.sources))
    def set_scene_item_enabled(self, scene, item_id, enabled):
        self.calls.append((scene, item_id, enabled))
        next(i for i in self.sources if i['sceneItemId']==item_id)['sceneItemEnabled']=enabled


class SelectionTests(unittest.TestCase):
    def test_exclusive_selection_and_repeated_press(self):
        client=FakeOBS();bg.select(client, "'Merica")
        self.assertEqual(client.calls, [('Loops',11,True),('Loops',10,False)])
        bg.select(client, "'Merica")
        self.assertEqual(len(client.calls),2)
    def test_missing_name_does_not_hide_current(self):
        client=FakeOBS()
        with self.assertRaises(ValueError):bg.select(client,'Missing')
        self.assertEqual(client.calls,[])



EXCLUSIVE = [{'scene': 'Background', 'source': name} for name in ('Desktop Screen', 'Loops', 'Office')]
EXCLUSIVE += [{'scene': 'SelectedFeed', 'source': 'Ada Camera'}, {'scene': 'Background', 'source': 'Pocketcam'}]


class ExclusiveOBS(FakeOBS):
    def __init__(self):
        super().__init__()
        self.scenes = {
            'Background': [{'sourceName': name, 'sceneItemId': i, 'sceneItemEnabled': False}
                           for i, name in enumerate(('Desktop Screen', 'Loops', 'Office', 'Pocketcam', 'Audio', 'Chryons'))],
            'SelectedFeed': [{'sourceName': name, 'sceneItemId': i, 'sceneItemEnabled': name == 'Face Camera'}
                             for i, name in enumerate(('Ada Camera', 'Face Camera'))],
        }
        for item in self.scenes['Background'][4:]:
            item['sceneItemEnabled'] = True

    def get_scene_list(self):
        return SimpleNamespace(current_program_scene_name='Portrait')

    def get_scene_item_list(self, scene):
        return SimpleNamespace(scene_items=copy.deepcopy(self.scenes[scene]))

    def set_scene_item_enabled(self, scene, item_id, enabled):
        self.calls.append((scene, item_id, enabled))
        next(i for i in self.scenes[scene] if i['sceneItemId'] == item_id)['sceneItemEnabled'] = enabled


def exclusive_settings(entry):
    return dict(entry, id=entry['source'], kind='item', exclusive=EXCLUSIVE)


class ExclusiveSelectionTests(unittest.TestCase):
    def enabled(self, client):
        return [(entry['scene'], entry['source']) for entry in EXCLUSIVE
                if next(i for i in client.scenes[entry['scene']] if i['sourceName'] == entry['source'])['sceneItemEnabled']]

    def test_every_pair_is_exclusive_and_selected_source_toggles_off(self):
        for first in EXCLUSIVE:
            for second in EXCLUSIVE:
                with self.subTest(first=first, second=second):
                    client = ExclusiveOBS()
                    bg.toggle_exclusive(client, exclusive_settings(first))
                    bg.toggle_exclusive(client, exclusive_settings(second))
                    expected = [] if first == second else [(second['scene'], second['source'])]
                    self.assertEqual(self.enabled(client), expected)
                    self.assertTrue(client.scenes['SelectedFeed'][1]['sceneItemEnabled'])
                    self.assertTrue(all(i['sceneItemEnabled'] for i in client.scenes['Background'][4:]))

    def test_external_multiple_selection_is_cleared(self):
        client = ExclusiveOBS()
        for item in client.scenes['Background'][:3]:
            item['sceneItemEnabled'] = True
        client.scenes['SelectedFeed'][0]['sceneItemEnabled'] = True
        bg.toggle_exclusive(client, exclusive_settings(EXCLUSIVE[-1]))
        self.assertEqual(self.enabled(client), [('Background', 'Pocketcam')])
        self.assertEqual(client.calls[0], ('Background', 3, True))

    def test_missing_duplicate_or_invalid_group_never_mutates(self):
        for mode in ('missing', 'duplicate', 'duplicate_group', 'outside_group'):
            with self.subTest(mode=mode):
                client = ExclusiveOBS()
                settings = exclusive_settings(EXCLUSIVE[0])
                if mode == 'missing':
                    client.scenes['SelectedFeed'].pop(0)
                elif mode == 'duplicate':
                    client.scenes['SelectedFeed'].append(copy.deepcopy(client.scenes['SelectedFeed'][0]))
                elif mode == 'duplicate_group':
                    settings['exclusive'] = EXCLUSIVE + [EXCLUSIVE[0]]
                else:
                    settings['source'] = 'Face Camera'
                with self.assertRaises(ValueError):
                    bg.toggle_exclusive(client, settings)
                self.assertEqual(client.calls, [])

    def test_visibility_automation_failure_is_reported(self):
        client = ExclusiveOBS()
        client.set_scene_item_enabled = lambda *args: None
        with self.assertRaisesRegex(RuntimeError, 'did not retain'):
            bg.toggle_exclusive(client, exclusive_settings(EXCLUSIVE[0]))

    def test_existing_obs_camera_exclusion_does_not_break_the_group(self):
        class NativeCameraOBS(ExclusiveOBS):
            def set_scene_item_enabled(self, scene, item_id, enabled):
                super().set_scene_item_enabled(scene, item_id, enabled)
                # The workstation's source-toggler.lua owns this camera rule.
                if scene == 'SelectedFeed' and enabled:
                    for item in self.scenes[scene]:
                        if item['sceneItemId'] != item_id:
                            item['sceneItemEnabled'] = False
        client = NativeCameraOBS()
        bg.toggle_exclusive(client, exclusive_settings(EXCLUSIVE[3]))
        self.assertEqual(self.enabled(client), [('SelectedFeed', 'Ada Camera')])
        self.assertFalse(client.scenes['SelectedFeed'][1]['sceneItemEnabled'])
        bg.toggle_exclusive(client, exclusive_settings(EXCLUSIVE[-1]))
        self.assertEqual(self.enabled(client), [('Background', 'Pocketcam')])
