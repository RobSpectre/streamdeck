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
    def test_audio_view_buttons_select_and_reflect_the_same_dial_view(self):
        from unittest.mock import Mock
        c = live.Controls()
        c.dials = live.Dials(Mock())
        settings = [dict(kind='dial_view', id=v, view=v) for v in ('studio', 'television')]
        self.assertEqual(c.snapshot(settings), {'studio': 1, 'television': 0})
        c.activate(settings[1])
        self.assertEqual(c.snapshot(settings), {'studio': 0, 'television': 1})
        c.activate(settings[0])
        self.assertEqual(c.dials.audio_view, 'studio')

    def test_context_keys_compact_and_other_telemetry_keys_navigate(self):
        from unittest.mock import call, patch
        c = live.Controls()
        c.codex = object()
        with patch.object(live, 'compact_agent') as compact, patch.object(live, 'navigate_agent') as navigate:
            c.activate({'kind': 'codex_telemetry', 'metric': 'context'})
            c.activate({'kind': 'agent_telemetry', 'agent': 'hermes', 'metric': 'context'})
            c.activate({'kind': 'agent_telemetry', 'agent': 'claude', 'metric': 'session'})
        self.assertEqual(compact.call_args_list, [call('codex', c.codex), call('hermes', c.codex)])
        navigate.assert_called_once_with('claude', 'session')

    def test_capsule_feedback_and_activation(self):
        from unittest.mock import Mock
        c = live.Controls()
        c.obs = Mock()
        c.obs.get_scene_collection_list.return_value = SimpleNamespace(current_scene_collection_name='hack.party')
        c.obs.get_input_settings.return_value = SimpleNamespace(input_kind='browser_source', input_settings={'css': ''})
        s = dict(kind='chyron_capsule', id='capsule', agent='codex', capsule='model', source='Token Chyron - Codex')
        self.assertEqual(c.snapshot([s]), {'capsule': 1})
        c.activate(s)
        args = c.obs.set_input_settings.call_args
        c.obs.get_input_settings.return_value.input_settings = args.args[1]
        self.assertEqual(c.snapshot([s]), {'capsule': 0})
        c.obs.get_scene_collection_list.return_value.current_scene_collection_name = 'Other'
        self.assertEqual(c.snapshot([s]), {'capsule': 2})

    def test_codex_buttons_only_respond_when_attention_is_active(self):
        from unittest.mock import patch
        c = live.Controls()
        state = [0]
        c.codex = SimpleNamespace(indicator=lambda: state[0])
        settings = {'kind': 'codex_response', 'id': 'codex:approve', 'decision': 'approve'}
        with patch.object(live, 'codex_respond') as respond:
            c.activate(settings)
            respond.assert_not_called()
            state[0] = 1
            self.assertEqual(c.snapshot([settings]), {'codex:approve': 1})
            c.activate(settings)
            respond.assert_called_once_with('approve', codex_ready=True)

    def test_hermes_approval_lights_all_supported_interaction_buttons(self):
        from unittest.mock import patch
        c = live.Controls()
        c.codex = SimpleNamespace(indicator=lambda: 0, actionable=lambda: [], auto_thread=None)
        settings = [
            {'kind': 'codex_response', 'id': 'codex:deny', 'decision': 'deny'},
            {'kind': 'codex_response', 'id': 'codex:approve', 'decision': 'approve'},
            {'kind': 'agent_action', 'id': 'agent-auto', 'decision': 'auto'},
            {'kind': 'agent_action', 'id': 'agent-allow-tool', 'decision': 'allow_tool'},
        ]
        pending = [{'agent': 'hermes', 'owner_pid': 123, 'dialog_pid': 456,
                    'extended': True, 'allow_tool': True}]
        with patch.object(live, 'cli_pending', return_value=pending), \
                patch.object(live, 'auto_enabled', return_value={}):
            self.assertEqual(c.snapshot(settings), {
                'codex:deny': 1, 'codex:approve': 1,
                'agent-auto': 1, 'agent-allow-tool': 1,
            })

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
    def test_hermes_config_key_reports_and_opens_isolated_demo(self):
        from unittest.mock import patch
        from tools import hermes_config
        settings = {'kind': 'hermes_config', 'id': 'hermes-config:mode'}
        c = live.Controls()
        with patch.object(hermes_config, 'state', return_value=2), \
             patch.object(hermes_config, 'toggle') as toggle:
            self.assertEqual(c.snapshot([settings]), {'hermes-config:mode': 2})
            c.activate(settings)
            toggle.assert_called_once_with()
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
class BattleKeyTests(unittest.TestCase):
    """The + XL battle keys: state from the timing feed, press fullscreens onboard."""

    ROWS = [{'ahead': {'tla': 'VER', 'colour': '#4781D7', 'position': 3},
             'behind': {'tla': 'NOR', 'colour': '#F47600', 'position': 4},
             'gap': 1.17, 'gap_text': '+1.170'}]
    SETTINGS = [{'kind': 'f1_battle', 'id': f'f1-battle:{slot}', 'slot': slot} for slot in range(8)]

    def controls(self, rows=None, available=True):
        c = live.Controls()
        from tools.f1_battles import BattleFeed
        c.f1 = BattleFeed()
        c.f1.rows, c.f1.available, c.f1.mode = self.ROWS if rows is None else rows, available, 'race'
        c.f1.value = lambda *a, **k: (c.f1.rows, available)
        return c

    def test_only_the_keys_a_battle_is_on_report_active(self):
        self.assertEqual(self.controls().snapshot(self.SETTINGS),
                         {f'f1-battle:{slot}': 0 if slot < 2 else 1 for slot in range(8)})

    def test_a_dead_timing_feed_hides_the_controls(self):
        self.assertEqual(self.controls([], available=False).snapshot(self.SETTINGS),
                         {f'f1-battle:{slot}': 1 for slot in range(8)})

    def test_the_press_fullscreens_the_driver_the_key_is_showing(self):
        from unittest.mock import patch
        c = self.controls()
        with patch.object(live.f1_keys, 'driver') as fullscreen:
            c.activate(self.SETTINGS[0])
            fullscreen.assert_called_once_with('VER')
            c.activate(self.SETTINGS[1])
            self.assertEqual(fullscreen.call_args.args, ('NOR',))

    def test_a_press_reads_the_cache_the_key_was_drawn_from(self):
        from unittest.mock import patch
        c = self.controls()
        with patch.object(c.f1, 'value') as read, patch.object(live.f1_keys, 'driver'):
            c.activate(self.SETTINGS[0])
        read.assert_not_called()

    def test_qualifying_press_uses_the_xl_driver_action_for_the_shown_driver(self):
        from unittest.mock import patch
        c = self.controls()
        c.f1.mode = 'qualifying'
        c.f1.rows = [self.ROWS[0]['behind']]
        with patch.object(live.f1_keys, 'driver') as driver, \
                patch.object(live.f1_keys, 'onboard') as fullscreen, patch.object(c.f1, 'value') as read:
            c.activate(self.SETTINGS[0])
            driver.assert_called_once_with('NOR')
            fullscreen.assert_not_called()
            read.assert_not_called()
        self.assertFalse(c.battle_dial_visible())

    def test_leaving_the_page_pauses_monitoring_and_clears_actions(self):
        from unittest.mock import patch
        c = self.controls()
        with patch.object(c.f1, 'value') as read:
            c.snapshot([])
            read.assert_not_called()
        self.assertFalse(c.battle_dial_visible())
        self.assertEqual(c.f1.slot(0)[0], 'hidden')
        with self.assertRaises(live.F1BattleError):
            c.activate(self.SETTINGS[0])

    def test_static_f1_keys_and_gap_dial_also_activate_the_shared_feed(self):
        from unittest.mock import patch
        for settings in ({'kind': 'f1_key', 'id': 'launch'},
                         {'kind': 'dial', 'id': 'gap', 'control': 'f1_gap_limit'}):
            c = self.controls()
            with patch.object(c.f1, 'value') as read:
                c.snapshot([settings])
                read.assert_called_once_with()

    def test_an_empty_key_refuses_instead_of_fullscreening_the_wrong_driver(self):
        from unittest.mock import patch
        c = self.controls()
        with patch.object(live.f1_keys, 'driver') as fullscreen:
            with self.assertRaises(live.F1BattleError):
                c.activate(self.SETTINGS[2])
            fullscreen.assert_not_called()
        with self.assertRaises(live.F1BattleError):
            self.controls([], available=False).activate(self.SETTINGS[0])

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
    def test_exclusive_keys_follow_live_visibility_and_toggle_off(self):
        from test_obs_background import ExclusiveOBS, EXCLUSIVE, exclusive_settings
        c = live.Controls()
        c.obs = ExclusiveOBS()
        settings = [exclusive_settings(entry) for entry in EXCLUSIVE]
        c.activate(settings[-1])
        self.assertEqual(c.snapshot(settings), {s['id']: int(s == settings[-1]) for s in settings})
        c.activate(settings[3])
        self.assertEqual(c.snapshot(settings), {s['id']: int(s == settings[3]) for s in settings})
        c.activate(settings[3])
        self.assertEqual(c.snapshot(settings), {s['id']: 0 for s in settings})

    def test_selection_updates_all_indicators_and_repeat_stays_selected(self):
        from test_obs_background import FakeOBS
        c=live.Controls();c.obs=FakeOBS()
        c.obs.get_scene_list=lambda: SimpleNamespace(current_program_scene_name='Portrait')
        settings=[{'id':'background:'+n,'kind':'background','scene':'Loops','source':n} for n in ['Space Highway',"'Merica",'Mars']]
        self.assertEqual(c.snapshot(settings),{'background:Space Highway':1,"background:'Merica":0,'background:Mars':0})
        c.activate(settings[2])
        self.assertEqual(c.snapshot(settings),{'background:Space Highway':0,"background:'Merica":0,'background:Mars':1})
        calls=len(c.obs.calls);c.activate(settings[2]);self.assertEqual(len(c.obs.calls),calls)

@unittest.skipIf(live is None, 'run with .venv/bin/python for live plugin tests')
class ThemeKeyTests(unittest.TestCase):
    """The chyron theme key: it reports the look the sources are on, and cycles it."""

    URL = 'http://127.0.0.1:8790/?agent=codex&bg=green&theme=nebius'

    class OBS:
        def __init__(self, url=None, fail=False):
            # Not a default argument from the enclosing class body: class scopes are
            # not visible to a nested class's defaults.
            self.url = url or 'http://127.0.0.1:8790/?agent=codex&bg=green&theme=nebius'
            self.fail = fail
        def get_scene_collection_list(self):
            return SimpleNamespace(current_scene_collection_name='hack.party')
        def get_scene_list(self):
            return SimpleNamespace(current_program_scene_name='Portrait')
        def get_input_settings(self, source):
            if self.fail:
                raise ConnectionError('OBS is gone')
            return SimpleNamespace(input_settings={'url': self.url})

    SETTINGS = {'kind': 'theme', 'id': 'theme:cycle', 'source': 'Token Chyron - Codex',
                'script': '/opt/chyrons/scripts/obs_chyrons.py', '_label_defaults': ['Theme']}

    def test_the_state_and_the_look_come_from_the_source_url(self):
        """The URL OBS is holding is the truth, so a look set by hand shows up too."""
        c = live.Controls()
        c.obs = self.OBS()
        self.assertEqual(c.snapshot([self.SETTINGS]), {'theme:cycle': 1})
        self.assertEqual(c.themes['theme:cycle'], 'nebius')

    def test_a_source_asked_for_a_look_is_not_a_look(self):
        c = live.Controls()
        c.obs = self.OBS(url='http://127.0.0.1:8790/?agent=codex&bg=green')
        self.assertEqual(c.snapshot([self.SETTINGS]), {'theme:cycle': 2})
        self.assertEqual(c.themes['theme:cycle'], '')

    def test_an_unreachable_obs_reads_as_unknown_rather_than_a_look(self):
        c = live.Controls()
        c.obs = self.OBS(fail=True)
        self.assertEqual(c.snapshot([self.SETTINGS]), {'theme:cycle': 2})
        self.assertIsNone(c.themes.get('theme:cycle'))

    def test_the_press_runs_the_same_script_a_hand_run_would(self):
        from unittest.mock import patch
        c = live.Controls()
        c.obs = self.OBS()
        with patch.object(live.subprocess, 'run') as run:
            c.activate(self.SETTINGS)
        run.assert_called_once_with([live.sys.executable, self.SETTINGS['script'],
                                     '--theme', 'next'], check=True, timeout=30)

    def test_the_key_art_is_found_by_name_and_missing_art_is_not_an_error(self):
        from unittest.mock import patch
        with patch.object(live, 'ROOT', Path('/nonexistent')):
            self.assertIsNone(live.theme_image('nebius'))
        self.assertIsNone(live.theme_image(''))
        art = live.theme_image('nebius')
        if art is not None:                    # the overlay repo draws these
            self.assertTrue(art.startswith('data:image/png;base64,'))


@unittest.skipIf(live is None, 'run with .venv/bin/python for live plugin tests')
class TrackStatusKeyTests(unittest.TestCase):
    """The Formula 1 page's keys under a flag: the status drawn on their own art."""

    SETTINGS = {'kind': 'f1_key', 'command': 'true',
                '_track_status': 'images/hackparty/art.png'}

    def test_a_key_with_no_art_is_left_alone(self):
        self.assertIsNone(live.track_image({'kind': 'f1_battle'}, live.track_status.YELLOW))

    def test_a_status_marks_the_key_with_its_own_art(self):
        from unittest.mock import patch
        with patch.object(live.track_status, 'key_image') as image:
            image.return_value = 'data:image/png;base64,marked'
            self.assertEqual(live.track_image(self.SETTINGS, live.track_status.RED),
                             'data:image/png;base64,marked')
        image.assert_called_once_with(self.SETTINGS['_track_status'], live.track_status.RED)

    def test_a_clear_track_sends_the_art_plain(self):
        # Sent even if this session has not marked the key yet: the app keeps the
        # last image it was sent, so a deck restarted under a flag is holding a
        # stale mark that only a plain image can clear.
        from unittest.mock import patch
        with patch.object(live.track_status, 'key_image') as image:
            image.return_value = 'data:image/png;base64,plain'
            self.assertEqual(live.track_image(self.SETTINGS, live.track_status.CLEAR),
                             'data:image/png;base64,plain')
        image.assert_called_once_with(self.SETTINGS['_track_status'], live.track_status.CLEAR)
