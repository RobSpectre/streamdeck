import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('migration', ROOT/'tools/build_opendeck.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class LiveControlIdTests(unittest.TestCase):
    """A live_control key's id is the identity the plugin keys its state by.

    The streaming process builds a per-key map from it the moment the page is
    shown, so a key without one takes the process down rather than failing on
    its own.
    """

    def build(self, control, temp, pages=('0',)):
        source = Path(temp)/'synthetic.json'
        source.write_text(json.dumps({'devices': {'TEST0000000001': {'page': 0, 'track_status_pages': list(pages),
            'buttons': {'0': {
            '0': {'state': 0, 'states': {'0': {'icon': 'images/formula_1/2026/VER.png',
                                               'text': 'VER', 'alignment': 'bottom'}},
                  'live_control': control}}}}}}))
        output = Path(temp)/'out'
        m.build(output, sources=[source])
        return output

    def test_a_live_control_key_without_an_id_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError) as error:
                self.build({'kind': 'f1_key', 'command': 'true'}, temp)
        self.assertIn('live_control key has no id', str(error.exception))

    def test_a_named_key_carries_its_command_and_its_status_art(self):
        with tempfile.TemporaryDirectory() as temp:
            output = self.build({'id': 'f1-key:test', 'kind': 'f1_key', 'command': 'true'}, temp)
            profile = json.loads((output/'profiles'/'sd-TEST0000000001'/'synthetic-json-page-01.json').read_text())
            key = profile['keys'][0]
            self.assertEqual(key['settings']['id'], 'f1-key:test')
            self.assertEqual(key['settings']['command'], 'true')
            self.assertEqual(len(key['states']), 1)
            self.assertEqual(key['current_state'], 0)
            self.assertTrue((output/key['settings']['_track_status']).is_file())

    def test_a_page_without_the_track_status_keeps_no_art(self):
        # Only the pages that wear the status carry the extra asset.
        with tempfile.TemporaryDirectory() as temp:
            output = self.build({'id': 'f1-key:test', 'kind': 'f1_key', 'command': 'true'}, temp, pages=())
            with open(output/'profiles'/'sd-TEST0000000001'/'synthetic-json-page-01.json') as handle:
                key = json.load(handle)['keys'][0]
        self.assertNotIn('_track_status', key['settings'])


class MigrationTests(unittest.TestCase):
    def test_broadcast_audio_views_preserve_end_dials_and_use_empty_light_adjacent_slots(self):
        page = json.loads((self.output/'profiles/sd-AD4MA61312Z98B/01 - broadcast.json').read_text())
        for position, view in [(24, 'studio'), (33, 'television')]:
            key = page['keys'][position]
            self.assertEqual(key['settings']['kind'], 'dial_view')
            self.assertEqual(key['settings']['view'], view)
            self.assertEqual(len(key['states']), 2)
            self.assertLess(key['current_state'], len(key['states']))
        for position, control in [(0, 'pc_volume'), (5, 'mic_volume')]:
            self.assertEqual(page['sliders'][position]['settings']['control'], control)
            self.assertNotIn('television', page['sliders'][position]['settings'])
        for position in range(1, 5):
            settings = page['sliders'][position]['settings']
            self.assertEqual(settings['television']['slot'], position-1)
            self.assertEqual(settings['television']['control'], 'television')
            # OpenDeck gives any nonempty native state title precedence over
            # setFeedback.title, preventing the Studio/TV label switch.
            self.assertTrue(all(s['text'] == '' for s in page['sliders'][position]['states']))

    def test_plus_xl_top_row_pocketcam_routes_the_background_layer(self):
        page = json.loads((self.output/'profiles/sd-AD4MA61312Z98B/01 - broadcast.json').read_text())
        pocket = page['keys'][8]
        self.assertEqual(pocket['settings']['_label_id'], 'broadcast-pocketcam-background')
        self.assertEqual(pocket['settings']['kind'], 'item')
        self.assertEqual(pocket['settings']['scene'], 'Background')
        self.assertEqual(pocket['settings']['source'], 'Pocketcam')
        group = [{'scene': 'Background', 'source': name} for name in ('Desktop Screen', 'Loops', 'Office')]
        group += [{'scene': 'SelectedFeed', 'source': 'Ada Camera'}, {'scene': 'Background', 'source': 'Pocketcam'}]
        for position in range(4, 9):
            self.assertEqual(page['keys'][position]['settings']['exclusive'], group)
        self.assertNotIn('exclusive', page['keys'][3]['settings'])
        self.assertNotIn('presentation', pocket['settings'])

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name)
        m.build(cls.output)
        cls.travel_temp = tempfile.TemporaryDirectory()
        cls.travel_output = Path(cls.travel_temp.name)
        m.build(cls.travel_output, sources=[ROOT/'opendeck-xl-travel.json'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        cls.travel_temp.cleanup()

    def test_every_page_and_navigation_target(self):
        count = 0
        for source in m.SOURCES:
            for serial, config in json.loads(source.read_text())['devices'].items():
                for page, buttons in config['buttons'].items():
                    path = self.output/'profiles'/('sd-'+serial)/(m.profile_name(source, page, serial)+'.json')
                    profile = json.loads(path.read_text())
                    self.assertEqual(len(profile['keys']), max(map(int, buttons))+1)
                    count += 1
                    def check(instance, position, index=0):
                        if instance is None:
                            return
                        self.assertEqual(instance['context'], f'Keypad.{position}.{index}')
                        self.assertLess(instance['current_state'], len(instance['states']))
                        for state in instance['states']:
                            if state['image']:
                                image = Path(state['image'])
                                self.assertFalse(image.is_absolute())
                                self.assertEqual(image.parts[:2], ('images', 'hackparty'))
                                self.assertTrue((self.output/image).is_file())
                        settings = instance['settings']
                        if instance['action']['uuid'].endswith('.switchprofile'):
                            self.assertTrue((self.output/'profiles'/settings['device']/(settings['profile']+'.json')).is_file())
                        if settings.get('down'):
                            subprocess.run(['sh', '-n'], input=settings['down'], text=True, check=True, capture_output=True)
                        for i, child in enumerate(instance['children'] or [], 1):
                            check(child, position, i)
                    for pos, key in enumerate(profile['keys']):
                        check(key, pos)
        self.assertEqual(count, 23)

    def test_navigation_hub_and_back_buttons(self):
        for serial, columns in [('CL37L2A01125', 8), ('AD4MA61312Z98B', 9)]:
            dev = self.output/'profiles'/('sd-' + serial)
            hub = json.loads((dev/'11 - Navigation.json').read_text())
            links = [key for key in hub['keys'] if key]
            destinations = {key['children'][-1]['settings']['profile'] for key in links}
            self.assertEqual(len(links), 5)
            self.assertEqual([i for i, k in enumerate(hub['keys']) if k], list(range(columns*3, columns*3+5)))
            for key in links:
                self.assertEqual(key['states'][0]['family'], 'DejaVu Sans')
                self.assertEqual(key['states'][0]['size'], 11)
                self.assertTrue(key['states'][0]['image'])
            self.assertEqual(destinations, {p.stem for p in dev.glob('*.json') if int(p.name[:2]) <= 5})
            self.assertEqual(json.loads(dev.with_suffix('.json').read_text())['selected_profile'], '11 - Navigation')
            for name in destinations:
                keys = json.loads((dev/(name+'.json')).read_text())['keys']
                if serial == 'AD4MA61312Z98B':
                    self.assertEqual(keys[0]['children'][-1]['settings']['profile'], '11 - Navigation')
                    self.assertEqual(keys[0]['children'][-1]['settings']['device'], 'sd-' + serial)
                if name == '01 - broadcast' and serial == 'AD4MA61312Z98B':
                    mic = next(k for k in keys if k and k['settings'].get('kind') == 'mic_mute')
                    self.assertEqual(mic['settings']['_label_id'], '98ce8a4f-ce1e-430b-ad23-89651ad54814')
            for key in links:
                self.assertEqual(len(key['children']), 2)
                peer, local = key['children']
                self.assertEqual(local['settings']['device'], 'sd-' + serial)
                self.assertNotEqual(peer['settings']['device'], local['settings']['device'])
                self.assertEqual(peer['settings']['profile'], local['settings']['profile'])

    def test_overflow_and_top_labels(self):
        for path in (self.output/'profiles/sd-CL37L2A01125').glob('*.json'):
            if path.stem not in ('11 - Navigation', '01 - broadcast', '05 - Formula 1', '03 - Vibecoding'):
                self.assertEqual([i for i, key in enumerate(json.loads(path.read_text())['keys']) if key], [])
        for path in (self.output/'profiles/sd-AD4MA61312Z98B').glob('*.json'):
            for key in json.loads(path.read_text())['keys']:
                if key:
                    self.assertTrue(all(s['alignment'] == 'top' for s in key['states']))

    def test_capsule_overflow_targets(self):
        keys = json.loads((self.output/'profiles/sd-CL37L2A01125/03 - Vibecoding.json').read_text())['keys']
        self.assertEqual([i for i, key in enumerate(keys) if key],
                         [*[row * 8 + col for row in range(3) for col in range(6)], 24])
        for row, agent in enumerate(('codex', 'claude', 'hermes')):
            for col, capsule in enumerate(('model', 'spark', 'speed', 'context', 'session', 'month')):
                key = keys[row * 8 + col]
                self.assertEqual(key['settings']['kind'], 'chyron_capsule')
                self.assertEqual(key['settings']['agent'], agent)
                self.assertEqual(key['settings']['capsule'], capsule)
                self.assertEqual(key['settings']['source'], 'Token Chyron - ' + agent.capitalize())
                self.assertEqual(len(key['states']), 3)

    def test_hermes_config_overflow_key(self):
        keys = json.loads((self.output/'profiles/sd-CL37L2A01125/03 - Vibecoding.json').read_text())['keys']
        key = keys[24]
        self.assertEqual(key['settings']['kind'], 'hermes_config')
        self.assertEqual(key['action']['uuid'], 'party.hack.status.control')
        self.assertEqual([state['text'] for state in key['states']], ['FRESH', 'HERMES?', 'MY CONFIG'])
        self.assertTrue(all(state['alignment'] == 'bottom' for state in key['states']))
        for state in key['states']:
            self.assertTrue((self.output/state['image']).is_file())
        self.assertEqual(key['settings']['_label_mode'], 'per_state')
        from tools import hermes_config
        self.assertEqual([key['states'][hermes_config.STATES[mode]]['text'] for mode in ('fresh', 'config')],
                         ['FRESH', 'MY CONFIG'])

    def test_broadcast_overflow_soundboard_copies(self):
        overflow = json.loads((self.output/'profiles/sd-CL37L2A01125/01 - broadcast.json').read_text())['keys']
        source = json.loads((self.output/'profiles/sd-AD4MA61312Z98B/02 - soundboard.json').read_text())['keys']
        controls = [k for k in source if k and k['settings'].get('_label_id') != 'navigation/back/1']
        self.assertEqual(len(controls), 17)
        self.assertEqual([i for i, k in enumerate(overflow) if k], [*range(15), 16, 17])
        for original, copied in zip(controls, [k for k in overflow if k]):
            self.assertEqual(original['settings'], copied['settings'])
            self.assertEqual(original['action']['uuid'], copied['action']['uuid'])
            for before, after in zip(original['states'], copied['states']):
                self.assertEqual({**before, 'alignment': 'bottom'}, after)

    def test_travel_navigation_is_standalone(self):
        for path in (self.travel_output/'profiles/sd-CL37L2A01125').glob('*.json'):
            for key in json.loads(path.read_text())['keys']:
                if key and key['action']['uuid'].endswith('.switchprofile'):
                    self.assertEqual(key['settings']['device'], 'sd-CL37L2A01125')

    def test_plus_xl_preserves_controls_and_local_navigation(self):
        old = self.output/'profiles/sd-CL37L2A01125'
        new = self.output/'profiles/sd-AD4MA61312Z98B'
        self.assertEqual({p.name for p in old.glob('*.json')},
                         {p.name for p in new.glob('*.json')})
        for path in old.glob('*.json'):
            after = json.loads((new/path.name).read_text())
            self.assertEqual(len(after['keys']), 36)
            if path.name == '01 - broadcast.json':
                self.assertEqual([d['settings']['control'] for d in after['sliders']],
                                 ['pc_volume', 'spotify', 'obs_volume', 'terminal_font', 'window_zoom', 'mic_volume'])
                for i, dial in enumerate(after['sliders']):
                    self.assertEqual(dial['context'], f'Encoder.{i}.0')
                    self.assertEqual(dial['action']['controllers'], ['Encoder'])
                    self.assertTrue((self.output/'plugins'/m.STATUS_PLUGIN/dial['action']['encoder']['layout']).is_file())
            elif path.name == '03 - Vibecoding.json':
                self.assertEqual([(d['settings']['agent'], d['settings']['parameter']) for d in after['sliders']],
                                 [(a, p) for a in ('codex', 'claude', 'hermes') for p in ('model', 'reasoning')])
                for dial in after['sliders']:
                    self.assertEqual(dial['action']['encoder']['layout'], 'agent-selector.json')
            elif path.name == '05 - Formula 1.json':
                # The rightmost dial sets how wide a gap still counts as a battle.
                self.assertEqual([d['settings']['control'] if d else None for d in after['sliders']],
                                 [None, None, None, None, None, 'f1_gap_limit'])
                self.assertEqual(after['sliders'][5]['settings']['title'], 'BATTLE GAP')
                self.assertEqual(after['sliders'][5]['action']['encoder']['layout'], 'dial-meter.json')
            else:
                self.assertEqual(after['sliders'], [None] * 6)
    def test_formula_one_driver_split(self):
        primary = json.loads((self.output/'profiles/sd-AD4MA61312Z98B/05 - Formula 1.json').read_text())['keys']
        overflow = json.loads((self.output/'profiles/sd-CL37L2A01125/05 - Formula 1.json').read_text())['keys']
        order = 'VER HAD LIN LAW LEC HAM SAI ALB GAS COL RUS ANT BOR HUL NOR PIA CAM BEA ALO STR BOT PER'.split()
        self.assertEqual([i for i, k in enumerate(overflow) if k], list(range(22)))
        for key, driver in zip(overflow, order):
            self.assertIn('--driver_abbreviation ' + driver, key['settings']['command'])
            self.assertEqual(key['states'][0]['alignment'], 'bottom')
        self.assertFalse(any('--driver_abbreviation' in k['settings'].get('command', '') for k in primary if k))
        self.assertEqual([i for i, k in enumerate(primary) if k],
                         sorted([0, 1, 2, 3, 9, 10, 11, 12, 18, 19, 20, 21, 27, 28, 29, 30,
                                 7, 8, 16, 17, 25, 26, 34, 35]))

    def test_every_formula_one_key_is_the_plugins_own(self):
        """The status is only drawn on the plugin's keys, so the page's keys are its.

        A plugin cannot write an image to a key another action owns - the app
        drops it - so every key on the Formula 1 pages carries this plugin's
        action with the command it used to run, and the art to mark it.
        """
        pages = {'sd-AD4MA61312Z98B': [1, 2, 3, 9, 10, 11, 12, 18, 19, 20, 21, 27, 28, 29, 30],
                 'sd-CL37L2A01125': list(range(22))}
        for device, slots in pages.items():
            keys = json.loads((self.output/f'profiles/{device}/05 - Formula 1.json').read_text())['keys']
            for slot in slots:
                key = keys[slot]
                self.assertEqual(key['action']['uuid'], m.STATUS_ACTION)
                self.assertTrue(key['action']['disable_automatic_states'])
                self.assertEqual(key['settings']['kind'], 'f1_key')
                self.assertTrue(key['settings']['command'])
                # One state, because the app still draws the key: the plugin only
                # replaces its image while a status is out.
                self.assertEqual(len(key['states']), 1)
                self.assertEqual(key['current_state'], 0)
                self.assertTrue((self.output/key['settings']['_track_status']).is_file())

    def test_the_navigation_key_and_the_battle_keys_carry_no_status_art(self):
        """Nothing to mark on a key the app owns, or on one the plugin draws."""
        keys = json.loads((self.output/'profiles/sd-AD4MA61312Z98B/05 - Formula 1.json').read_text())['keys']
        self.assertEqual(keys[0]['action']['uuid'], 'opendeck.multiaction')
        self.assertNotIn('_track_status', keys[0]['settings'])
        for pos in (7, 8, 16, 17, 25, 26, 34, 35):
            self.assertEqual(keys[pos]['settings']['kind'], 'f1_battle')
            self.assertNotIn('_track_status', keys[pos]['settings'])

    def test_formula_one_battle_keys(self):
        """The rightmost two + XL columns: leader left, trailer right, per row."""
        keys = json.loads((self.output/'profiles/sd-AD4MA61312Z98B/05 - Formula 1.json').read_text())['keys']
        positions = [7, 8, 16, 17, 25, 26, 34, 35]
        for slot, pos in enumerate(positions):
            key = keys[pos]
            self.assertEqual(key['settings']['kind'], 'f1_battle')
            self.assertEqual(key['settings']['slot'], slot)
            self.assertEqual(key['settings']['id'], f'f1-battle:{slot}')
            self.assertEqual(key['action']['uuid'], m.STATUS_ACTION)
            self.assertTrue(key['action']['disable_automatic_states'])
            # setImage always targets state 0, so that is the state that must show.
            self.assertEqual(key['current_state'], 0)
            self.assertEqual(len(key['states']), 3)
            self.assertFalse(key['states'][0]['text'])
            for state in key['states']:
                self.assertTrue((self.output/state['image']).is_file())
            self.assertEqual(key['settings']['_label_id'], f'f1-battle/{slot}')
        # Columns 4-6 and the rest of 7-8 stay empty: only these eight are ours.
        self.assertEqual([i for i, k in enumerate(keys) if k and k['settings'].get('kind') == 'f1_battle'],
                         sorted(positions))

    def test_bundled_icons_match_source(self):
        source = json.loads((ROOT/m.CURRENT).read_text())
        for serial, config in source['devices'].items():
            for page, buttons in config['buttons'].items():
                profile = json.loads((self.output/'profiles'/('sd-'+serial)/(m.profile_name(ROOT/m.CURRENT, page, serial)+'.json')).read_text())
                for pos, button in buttons.items():
                    for i, state in enumerate(button['states'].values()):
                        if state.get('icon') and not button.get('live_control'):
                            bundled = profile['keys'][int(pos)]['states'][i]['image']
                            self.assertEqual((self.output/bundled).read_bytes(), (ROOT/state['icon']).read_bytes())
        self.assertEqual(len(list((self.output/'profiles').glob('*/*.json'))), 23)

    def test_reorganized_navigation_and_empty_pages(self):
        dev = self.travel_output/'profiles/sd-CL37L2A01125'
        names = ['01 - broadcast', '02 - soundboard', '04 - Background Selection', '05 - Formula 1', '06 - Formula 1 Page 2']
        for name in names:
            self.assertTrue((dev/(name+'.json')).is_file())
        soundboard = json.loads((dev/(names[1]+'.json')).read_text())
        formula = json.loads((dev/(names[3]+'.json')).read_text())
        self.assertIsNone(soundboard['keys'][7])
        self.assertEqual(formula['keys'][0]['settings']['profile'], '11 - Navigation')
        for page in (3, 7):
            name = '03 - Vibecoding' if page == 3 else f'{page:02} - Page {page}'
            profile = json.loads((dev/(name+'.json')).read_text())
            occupied = [(i, k) for i,k in enumerate(profile['keys']) if k]
            self.assertEqual([i for i,k in occupied], [i for i in range(32) if i != 7] if page == 3 else [0])
            self.assertEqual(profile['keys'][0]['settings']['profile'], '11 - Navigation')
            if page == 3:
                # 8 hands the whole overlay its next look *and* reports the one it is
                # on: a live control, so the plugin can set its image and title from
                # the source URL, running the same command a hand-run would.
                self.assertEqual(profile['keys'][8]['settings']['kind'], 'theme')
                self.assertEqual(profile['keys'][8]['settings']['id'], 'theme:cycle')
                self.assertTrue(profile['keys'][8]['settings']['script'].endswith('obs_chyrons.py'))
                self.assertEqual(len(profile['keys'][8]['states']), 3)
                for pos, decision in [(24, 'deny'), (25, 'approve')]:
                    key = profile['keys'][pos]
                    self.assertEqual(key['settings']['decision'], decision)
                    self.assertEqual(key['settings']['kind'], 'codex_response')
                    self.assertEqual(key['current_state'], 0)
                    self.assertNotEqual(key['states'][0]['image'], key['states'][1]['image'])
                for pos in range(1, 7):
                    self.assertEqual(profile['keys'][pos]['settings']['kind'], 'codex_telemetry')
                    self.assertFalse(profile['keys'][pos]['states'][0]['show'])
                for name, start in [('claude', 9), ('hermes', 17)]:
                    for pos in range(start, start+6):
                        self.assertEqual(profile['keys'][pos]['settings']['agent'], name)
                        self.assertFalse(profile['keys'][pos]['states'][0]['show'])
        self.assertEqual(len(list(dev.glob('*.json'))), 11)

    def test_all_backgrounds_and_broadcast_soundboard_copies(self):
        import shlex
        dev = self.travel_output/'profiles/sd-CL37L2A01125'
        page = json.loads((dev/'04 - Background Selection.json').read_text())
        catalog = json.loads((ROOT/'obs_backgrounds.json').read_text())['backgrounds']
        backgrounds = [k for k in page['keys'] if k and k['settings'].get('kind') == 'background']
        self.assertEqual(len(backgrounds), len(catalog))
        self.assertEqual({k['settings']['source'] for k in backgrounds}, set(catalog))
        for key in backgrounds:
            self.assertEqual(len(key['states']), 3)
            self.assertTrue(key['action']['disable_automatic_states'])
            self.assertEqual(key['settings']['scene'], 'Loops')
        broadcast = json.loads((dev/'01 - broadcast.json').read_text())
        soundboard = json.loads((dev/'02 - soundboard.json').read_text())
        for index, label in zip((18, 19), ('Rap Horn', 'Winner')):
            copied = broadcast['keys'][index]
            original = next(k for k in soundboard['keys'] if k and k['states'][0]['text'] == label)
            self.assertEqual(copied['states'], original['states'])
            self.assertEqual({k:v for k,v in copied['settings'].items() if not k.startswith('_label_')}, {k:v for k,v in original['settings'].items() if not k.startswith('_label_')})
        pocket = broadcast['keys'][26]
        self.assertEqual(pocket['settings']['kind'], 'background')
        self.assertEqual(pocket['settings']['scene'], 'Loops')
        self.assertEqual(pocket['settings']['source'], 'Pocketcam')
        self.assertTrue(any(k and k['settings'].get('id') == 'effect:Vibing' for k in soundboard['keys']))
        # Columns 27-29 used to be the Crickets/Laughs/Sad sound effects. They are
        # chyron toggles now: the same `item` control the camera keys use, on the
        # Chryons scene, so a press shows or hides that agent's chyron.
        for index, agent in zip((27, 28, 29), ('codex', 'claude', 'hermes')):
            key = broadcast['keys'][index]
            self.assertEqual(key['settings']['kind'], 'item')
            self.assertEqual(key['settings']['scene'], 'Chryons')
            self.assertEqual(key['settings']['source'], f'Token Chyron - {agent.title()}')
            self.assertEqual(key['states'][0]['text'], agent.title())
            self.assertEqual(len(key['states']), 3)

    def test_live_control_states(self):
        path = self.travel_output/'profiles/sd-CL37L2A01125/01 - broadcast.json'
        profile = json.loads(path.read_text())
        live = [k for k in profile['keys'] if k and k['action']['uuid'] == m.STATUS_ACTION]
        self.assertEqual(len(live), 22)
        for key in live:
            self.assertTrue(key['action']['disable_automatic_states'])
            self.assertEqual(len(key['states']), 3)
            expected = 0 if key['settings']['kind'] in ('audio_mode', 'mic_mute') else 2
            self.assertEqual(key['current_state'], expected)
            for state in key['states']:
                self.assertTrue((self.travel_output/state['image']).is_file())
        self.assertEqual(profile['keys'][6]['settings']['source'], 'Office')
        self.assertEqual(profile['keys'][5]['settings']['source'], 'Loops')

    def test_soundboard_effect_coverage(self):
        dev=self.travel_output/'profiles/sd-CL37L2A01125'
        page=json.loads((dev/'02 - soundboard.json').read_text())
        indices=[*range(1,7),*range(8,16),23]
        for pos in indices:
            key=page['keys'][pos]
            self.assertEqual(key['settings']['kind'],'effect')
            self.assertEqual(len(key['states']),3)
            self.assertTrue(key['settings']['targets'])
        self.assertTrue(page['keys'][0]['action']['uuid'].endswith('.switchprofile'))
        self.assertIsNone(page['keys'][7])
        self.assertTrue(page['keys'][16]['action']['uuid'].endswith('.runcommand'))

    def test_current_selection_and_blur_toggle(self):
        dev = self.travel_output/'profiles'/'sd-CL37L2A01125'
        selection = json.loads(dev.with_suffix('.json').read_text())
        self.assertEqual(selection['selected_profile'], m.profile_name(ROOT/m.CURRENT, 10, 'CL37L2A01125'))
        blur = json.loads((dev/(m.profile_name(ROOT/m.CURRENT, 0, 'CL37L2A01125')+'.json')).read_text())['keys'][12]
        self.assertEqual(blur['action']['uuid'], 'opendeck.toggleaction')
        self.assertEqual([s['text'] for s in blur['states']], ['Blur OFF', 'Blur ON'])
        for index in (0, 1):
            self.assertIn('control_obs_blur.py '+['on', 'off'][index], blur['children'][index]['settings']['down'])

    def test_shell_quoting_working_directory_and_literal_text(self):
        with tempfile.TemporaryDirectory(prefix="deck ' spaces ") as directory:
            root = Path(directory)
            # Exercise the generated shell with fake input, without touching any desktop apps.
            (root/'xdotool').write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> args.txt\n')
            (root/'xdotool').chmod(0o755)
            s = {'command': 'pwd > cwd.txt', 'keys': 'ctrl+page_down', 'write': "a'\n$(touch BAD)"}
            converted = m.convert_state(s, Path('test.json'), 'sd-test', {'0': {}}, 0, root, set())
            import os
            env = dict(os.environ, PATH=str(root)+':'+os.environ['PATH'])
            subprocess.run(['sh', '-c', converted['settings']['down']], env=env, check=True)
            self.assertEqual((root/'cwd.txt').read_text().strip(), directory)
            self.assertIn('ctrl+Page_Down', (root/'args.txt').read_text())
            self.assertIn(s['write'], (root/'args.txt').read_text())
            self.assertFalse((root/'BAD').exists())

    def test_generated_files_are_current(self):
        for path in self.output.rglob('*.json'):
            actual = json.loads(path.read_text())
            expected = json.loads((ROOT/'opendeck'/path.relative_to(self.output)).read_text())
            if path.name == 'migration-report.json':
                actual.pop('retired_profiles', None)
                expected.pop('retired_profiles', None)
            self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
