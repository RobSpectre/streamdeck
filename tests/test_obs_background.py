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
