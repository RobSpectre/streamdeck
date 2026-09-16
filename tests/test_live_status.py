import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location('live',Path(__file__).resolve().parents[1]/'tools/opendeck_status_plugin.py')
live=importlib.util.module_from_spec(spec)
# The migration suite can run under system Python without optional runtime packages.
try:
    spec.loader.exec_module(live)
except ModuleNotFoundError:
    live=None

@unittest.skipIf(live is None, 'run with .venv/bin/python for live plugin tests')
class StatusTests(unittest.TestCase):
    def test_scene_switch_is_selection_not_toggle(self):
        c=live.Controls()
        class OBS:
            current='Portrait'
            def get_scene_collection_list(self):return SimpleNamespace(current_scene_collection_name='hack.party')
            def get_scene_list(self):return SimpleNamespace(current_program_scene_name=self.current)
            def set_current_program_scene(self,name):self.current=name
        c.obs=OBS()
        scenes=[{'id':'PiP','kind':'scene','scene':'PiP'},{'id':'Portrait','kind':'scene','scene':'Portrait'}]
        self.assertEqual(c.snapshot(scenes),{'PiP':0,'Portrait':1})
        c.activate(scenes[0]);c.activate(scenes[0])
        self.assertEqual(c.snapshot(scenes),{'PiP':1,'Portrait':0})
    def test_unknown_light_is_not_reported_off(self):
        c=live.Controls()
        def broken(*args):raise OSError()
        c.light=broken
        self.assertEqual(c.snapshot([{'id':'Key','kind':'light','light':'Key'}]),{'Key':2})
    def test_chroma_switches_both_sources(self):
        c=live.Controls()
        class OBS:
            calls=[]
            def get_scene_collection_list(self):return SimpleNamespace(current_scene_collection_name='hack.party')
            def get_scene_item_list(self,name):return SimpleNamespace(scene_items=[{'sourceName':'with','sceneItemId':1,'sceneItemEnabled':False},{'sourceName':'without','sceneItemId':2,'sceneItemEnabled':True}])
            def set_scene_item_enabled(self,*args):self.calls.append(args)
        c.obs=OBS()
        c.activate({'kind':'item','scene':'Face Camera','source':'with','complement':'without'})
        self.assertEqual(c.obs.calls,[('Face Camera',1,True),('Face Camera',2,False)])

@unittest.skipIf(live is None, 'run with .venv/bin/python for live plugin tests')
class EffectTests(unittest.TestCase):
    def test_effect_pair_toggles_together_and_partial_state_turns_off(self):
        c=live.Controls()
        class OBS:
            def __init__(self):
                self.items={'Sound Effects':[{'sourceName':'Mario Win','sceneItemId':1,'sceneItemEnabled':False}], 'Scene Overlays':[{'sourceName':'Confetti','sceneItemId':6,'sceneItemEnabled':False}]}
                self.calls=[]
            def get_scene_collection_list(self):return SimpleNamespace(current_scene_collection_name='hack.party')
            def get_scene_list(self):return SimpleNamespace(current_program_scene_name='Portrait')
            def get_scene_item_list(self,name):return SimpleNamespace(scene_items=self.items[name])
            def set_scene_item_enabled(self,scene,index,enabled):
                self.calls.append((scene,index,enabled))
                next(i for i in self.items[scene] if i['sceneItemId']==index)['sceneItemEnabled']=enabled
        c.obs=OBS();s={'id':'effect:Winner','kind':'effect','targets':[{'scene':'Sound Effects','source':'Mario Win'},{'scene':'Scene Overlays','source':'Confetti'}]}
        self.assertEqual(c.snapshot([s])[s['id']],0)
        c.activate(s)
        self.assertEqual(c.snapshot([s])[s['id']],1)
        self.assertEqual(len(c.obs.calls),2)
        c.obs.items['Sound Effects'][0]['sceneItemEnabled']=False
        self.assertEqual(c.snapshot([s])[s['id']],1)
        c.activate(s)
        self.assertEqual(c.snapshot([s])[s['id']],0)
        s['targets'].append({'scene':'Sound Effects','source':'Missing'})
        calls=len(c.obs.calls)
        with self.assertRaises(ValueError):c.activate(s)
        self.assertEqual(len(c.obs.calls),calls)
        self.assertEqual(c.snapshot([s])[s['id']],2)

@unittest.skipIf(live is None, 'run with .venv/bin/python for live plugin tests')
class BackgroundIndicatorTests(unittest.TestCase):
    def test_selection_updates_all_indicators_and_repeat_stays_selected(self):
        from test_obs_background import FakeOBS
        c=live.Controls();c.obs=FakeOBS()
        c.obs.get_scene_list=lambda: SimpleNamespace(current_program_scene_name='Portrait')
        settings=[{'id':'background:'+n,'kind':'background','scene':'Loops','source':n} for n in ['Space Highway',"'Merica",'Mars']]
        self.assertEqual(c.snapshot(settings),{'background:Space Highway':1,"background:'Merica":0,'background:Mars':0})
        c.activate(settings[2])
        self.assertEqual(c.snapshot(settings),{'background:Space Highway':0,"background:'Merica":0,'background:Mars':1})
        calls=len(c.obs.calls);c.activate(settings[2]);self.assertEqual(len(c.obs.calls),calls)
