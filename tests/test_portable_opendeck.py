import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import portable_opendeck as portable


class PortableTests(unittest.TestCase):
    def test_laptop_retains_coding_identities_without_studio_controls(self):
        data = json.loads((portable.ROOT/portable.SOURCE).read_text())
        portable.validate_layout(data)
        laptop = data['devices'][portable.SERIAL]
        desktop = json.loads((portable.ROOT/'opendeck-layout.json').read_text())['devices'][portable.SERIAL]
        self.assertEqual(laptop['page'], 2)
        self.assertEqual(laptop['dials']['2'], desktop['dials']['2'])
        for pos, b in laptop['buttons']['2'].items():
            if b:
                self.assertEqual(b, desktop['buttons']['2'][pos])
        data['devices'][portable.SERIAL]['dials']['0']['2'] = {'control': 'obs_volume'}
        with self.assertRaises(ValueError):
            portable.validate_layout(data)

    def test_archive_builds_after_relocation_and_has_no_runtime_state(self):
        with tempfile.TemporaryDirectory(prefix='portable space ') as folder:
            root = Path(folder)
            archive = root/'rig.tar.gz'
            portable.export(archive)
            with tarfile.open(archive) as tar:
                names = tar.getnames()
                self.assertFalse(any(x.endswith(('/lights.json', '/state.json', '/runtime.json', '/portable-machine.json')) for x in names))
                self.assertFalse(any('/.venv/' in x or '.bak-' in x for x in names))
                tar.extractall(root, filter='data')
            relocated = root/'streamdeck-laptop'
            result = subprocess.run([sys.executable, str(relocated/'tools/portable_opendeck.py'),
                                     'build', '--output', str(root/'bundle')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            launcher = (root/'bundle/plugins/party.hack.status.sdPlugin/launch.sh').read_text()
            self.assertIn(str(relocated), launcher)
            self.assertNotIn(str(portable.ROOT), launcher)
            # Source Hermes plugin resolves its new checkout with no desktop path.
            script = "import importlib.util; s=importlib.util.spec_from_file_location('hp','integrations/hermes-opendeck/__init__.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.ROOT)"
            result = subprocess.run([sys.executable, '-c', script], cwd=relocated, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(relocated))

    def test_install_refuses_running_app_and_backs_up_entire_config(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'opendeck'
            (config/'plugins/com.amansprojects.starterpack.sdPlugin').mkdir(parents=True)
            (config/'settings.json').write_text('{"custom":true}')
            (config/'plugins/other').mkdir()
            (config/'plugins/other/keep').write_text('keep')
            with patch.object(portable.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaisesRegex(ValueError, 'Quit OpenDeck'):
                    portable.install(config)
            with patch.object(portable.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
                portable.install(config)
            backup, = Path(folder).glob('opendeck.laptop-backup-*')
            self.assertEqual((backup/'settings.json').read_text(), '{"custom":true}')
            self.assertEqual((config/'plugins/other/keep').read_text(), 'keep')
            selector = json.loads((config/f'profiles/sd-{portable.SERIAL}.json').read_text())
            self.assertEqual(selector['selected_profile'], '03 - Laptop Vibecoding')

    def test_no_obs_connection_for_laptop_snapshot(self):
        from tools import opendeck_status_plugin as plugin
        # Local controls do not require a lights file at startup.
        with tempfile.TemporaryDirectory() as folder, patch.object(plugin, 'ROOT', Path(folder)):
            backend = plugin.Controls()
            self.assertEqual(backend.lights, {})
            with patch.object(backend, 'obs_client', side_effect=AssertionError('OBS must not be queried')):
                self.assertEqual(backend.snapshot([{'kind': 'suno_media', 'id': 'play'}]), {'play': 0})
