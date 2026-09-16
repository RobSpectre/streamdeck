import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_obs_blur import FILTER, KIND, SETTINGS, set_blur

class FakeOBS:
    def __init__(self):
        self.current = 'Portrait'
        self.filters = {'Portrait': [], 'Desktop': [{'filterName':'Other blur','filterKind':KIND,'filterEnabled':True}]}
    def get_scene_collection_list(self):
        return SimpleNamespace(current_scene_collection_name='hack.party')
    def get_scene_list(self):
        return SimpleNamespace(current_program_scene_name=self.current, scenes=[{'sceneName':n} for n in self.filters])
    def get_source_filter_list(self, name):
        return SimpleNamespace(filters=self.filters[name])
    def create_source_filter(self, source, name, kind, settings):
        self.filters[source].append({'filterName':name,'filterKind':kind,'filterEnabled':True})
    def set_source_filter_settings(self, source, name, settings, overlay):
        self.settings = settings.copy()
    def set_source_filter_enabled(self, source, name, enabled):
        next(f for f in self.filters[source] if f['filterName']==name)['filterEnabled']=enabled
    def get_source_filter(self, source, name):
        return SimpleNamespace(filter_enabled=next(f for f in self.filters[source] if f['filterName']==name)['filterEnabled'])

class BlurTests(unittest.TestCase):
    def test_on_is_idempotent_and_off_clears_managed_scenes_only(self):
        c=FakeOBS();set_blur(c, True);set_blur(c, True)
        self.assertEqual(len(c.filters['Portrait']),1)
        self.assertEqual(c.settings['blur_algorithm'], 1)
        self.assertEqual(c.settings['blur_type'], 1)
        c.current='Desktop';set_blur(c,True);set_blur(c,False)
        self.assertFalse(c.get_source_filter('Portrait',FILTER).filter_enabled)
        self.assertFalse(c.get_source_filter('Desktop',FILTER).filter_enabled)
        self.assertTrue(c.get_source_filter('Desktop','Other blur').filter_enabled)
