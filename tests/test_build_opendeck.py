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


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name)
        m.build(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

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
        self.assertEqual(count, 11)

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
        self.assertEqual(len(list((self.output/'profiles').glob('*/*.json'))), 11)

    def test_reorganized_navigation_and_empty_pages(self):
        dev = self.output/'profiles/sd-CL37L2A01125'
        names = ['01 - broadcast', '02 - soundboard', '03 - Background Selection', '04 - Formula 1', '05 - Formula 1 Page 2']
        for name in names:
            self.assertTrue((dev/(name+'.json')).is_file())
        soundboard = json.loads((dev/(names[1]+'.json')).read_text())
        formula = json.loads((dev/(names[3]+'.json')).read_text())
        self.assertEqual(soundboard['keys'][7]['settings']['profile'], names[2])
        self.assertEqual(formula['keys'][0]['settings']['profile'], names[2])
        for page in (6, 7):
            profile = json.loads((dev/f'{page:02} - Page {page}.json').read_text())
            occupied = [(i, k) for i,k in enumerate(profile['keys']) if k]
            self.assertEqual([i for i,k in occupied], [0, 7])
            self.assertTrue(all(k['action']['uuid'].endswith('.switchprofile') for i,k in occupied))
        self.assertEqual(len(list(dev.glob('*.json'))), 10)

    def test_all_backgrounds_and_broadcast_soundboard_copies(self):
        import shlex
        dev = self.output/'profiles/sd-CL37L2A01125'
        page = json.loads((dev/'03 - Background Selection.json').read_text())
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
        for index, label in zip((18, 19, 26, 27, 28, 29), ('Rap Horn', 'Winner', 'Vibing', 'Crickets', 'Laughs', 'Sad')):
            copied = broadcast['keys'][index]
            original = next(k for k in soundboard['keys'] if k and k['states'][0]['text'] == label)
            self.assertEqual(copied['states'], original['states'])
            self.assertEqual({k:v for k,v in copied['settings'].items() if not k.startswith('_label_')}, {k:v for k,v in original['settings'].items() if not k.startswith('_label_')})

    def test_live_control_states(self):
        path = self.output/'profiles/sd-CL37L2A01125/01 - broadcast.json'
        profile = json.loads(path.read_text())
        live = [k for k in profile['keys'] if k and k['action']['uuid'] == m.STATUS_ACTION]
        self.assertEqual(len(live), 22)
        for key in live:
            self.assertTrue(key['action']['disable_automatic_states'])
            self.assertEqual(len(key['states']), 3)
            expected = 0 if key['settings']['kind'] in ('audio_mode', 'mic_mute') else 2
            self.assertEqual(key['current_state'], expected)
            for state in key['states']:
                self.assertTrue((self.output/state['image']).is_file())
        self.assertEqual(profile['keys'][6]['settings']['source'], 'Office')
        self.assertEqual(profile['keys'][5]['settings']['source'], 'Loops')

    def test_soundboard_effect_coverage(self):
        dev=self.output/'profiles/sd-CL37L2A01125'
        page=json.loads((dev/'02 - soundboard.json').read_text())
        indices=[*range(1,7),*range(8,16),23]
        for pos in indices:
            key=page['keys'][pos]
            self.assertEqual(key['settings']['kind'],'effect')
            self.assertEqual(len(key['states']),3)
            self.assertTrue(key['settings']['targets'])
        for pos in (0,7):
            self.assertTrue(page['keys'][pos]['action']['uuid'].endswith('.switchprofile'))
        self.assertTrue(page['keys'][16]['action']['uuid'].endswith('.runcommand'))

    def test_current_selection_and_blur_toggle(self):
        dev = self.output/'profiles'/'sd-CL37L2A01125'
        selection = json.loads(dev.with_suffix('.json').read_text())
        self.assertEqual(selection['selected_profile'], m.profile_name(ROOT/m.CURRENT, 1, 'CL37L2A01125'))
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
