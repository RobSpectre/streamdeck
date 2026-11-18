import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, Mock

from tools import hermes_config as demo


class HermesConfigTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'control'
        demo.invalidate()
        self.addCleanup(demo.invalidate)

    def container(self, status='running', owned=True):
        return {'Id': 'exact-container-id', 'Config': {'Labels': {demo.LABEL: '1' if owned else 'other'}},
                'State': {'Status': status, 'Running': status == 'running'}}

    def test_container_has_no_host_mounts_or_credential_forwarding(self):
        command = demo.create_command()
        self.assertEqual(command[-1], demo.IMAGE)
        self.assertIn('no-new-privileges', command)
        self.assertEqual(command[command.index('--cap-drop')+1], 'ALL')
        self.assertEqual(command[command.index('--user')+1], '10001:10001')
        self.assertEqual(command[command.index('--network')+1], 'bridge')
        for flag in ['--mount', '--volume', '-v', '--env', '-e', '--env-file', '--privileged', '--pid', '--device']:
            self.assertNotIn(flag, command)
        self.assertEqual(demo.DOCKER, ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock'])

    def test_refuse_name_collision(self):
        with patch.object(demo, 'inspect', return_value=self.container(owned=False)), patch.object(demo, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'another container'):
                demo.discard_stopped()
            run.assert_not_called()

    def test_reset_never_kills_running_demo(self):
        with patch.object(demo, 'managed_container', return_value=self.container()), patch.object(demo, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'never killed'):
                demo.discard_stopped()
            run.assert_not_called()

    def test_reset_removes_only_exact_stopped_container(self):
        with patch.object(demo, 'managed_container', return_value=self.container('exited')), patch.object(demo, 'run') as run:
            demo.discard_stopped()
            run.assert_called_once_with('rm', 'exact-container-id')

    def test_switch_back_preserves_host_and_demo(self):
        host = Path(self.temp.name)/'.hermes'
        host.mkdir()
        for name in ['active_profile', 'state.db', 'config.yaml']:
            (host/name).write_text('sentinel-'+name)
        before = {p.name: p.read_bytes() for p in host.iterdir()}
        demo.write_selection({'mode': 'fresh', 'terminal_pid': 123}, self.root)
        with patch('tools.agent_navigation.focus_agent') as focus, patch.object(demo, 'run') as run:
            self.assertEqual(demo.set_mode(self.root, 'config'), 'config')
            focus.assert_called_once_with('hermes')
            run.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in host.iterdir()})
        self.assertEqual(demo.read_selection(self.root)['terminal_pid'], 123)
        self.assertEqual(demo.mode(self.root), 'config')

    def test_closed_demo_returns_to_config(self):
        demo.write_selection({'mode': 'fresh', 'started': 0}, self.root)
        with patch.object(demo, 'managed_container', return_value=self.container('exited')):
            self.assertEqual(demo.mode(self.root), 'config')
        with patch.object(demo, 'managed_container', return_value=self.container()):
            self.assertEqual(demo.mode(self.root), 'fresh')

    def test_live_demo_is_focused_without_recreating(self):
        with patch.object(demo, 'available', return_value=True), \
             patch.object(demo, 'managed_container', return_value=self.container()), \
             patch.object(demo, 'focus_demo') as focus, patch.object(demo, 'run') as run:
            self.assertEqual(demo.set_mode(self.root, 'fresh'), 'fresh')
            focus.assert_called_once()
            run.assert_not_called()

    def test_new_demo_uses_dedicated_attach_helper(self):
        with patch.object(demo, 'available', return_value=True), \
             patch.object(demo, 'managed_container', return_value=None), \
             patch.object(demo, 'run') as docker, patch('subprocess.run') as terminal:
            demo.set_mode(self.root, 'fresh')
            docker.assert_called_once_with(*demo.create_command())
            command = terminal.call_args.args[0]
            self.assertEqual(command[0], '/usr/bin/gnome-terminal')
            self.assertEqual(command[-2:], [str(Path(demo.__file__).resolve()), '--attach'])
            self.assertEqual(demo.read_selection(self.root)['mode'], 'fresh')

    def test_image_missing_does_not_change_host_or_launch(self):
        with patch.object(demo, 'available', return_value=False), patch.object(demo, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Prepare'):
                demo.set_mode(self.root, 'fresh')
            run.assert_not_called()
            self.assertEqual(demo.mode(self.root), 'config')

    def test_failed_launch_discards_only_stopped_demo(self):
        with patch.object(demo, 'available', return_value=True), \
             patch.object(demo, 'managed_container', return_value=None), \
             patch.object(demo, 'discard_stopped') as discard, patch.object(demo, 'run'), \
             patch('subprocess.run', side_effect=OSError('no terminal')):
            with self.assertRaises(OSError):
                demo.set_mode(self.root, 'fresh')
            self.assertEqual(discard.call_count, 2)
            self.assertEqual(demo.mode(self.root), 'config')

    def test_state_failure_is_unavailable(self):
        with patch.object(demo, 'available', side_effect=RuntimeError('offline')):
            self.assertEqual(demo.state(self.root), 1)

    def test_key_state_indexes_keep_existing_label_identity(self):
        source = json.loads((demo.ROOT/'opendeck-layout.json').read_text())
        button = source['devices']['CL37L2A01125']['buttons']['2']['24']
        self.assertEqual(button['live_control']['kind'], 'hermes_config')
        self.assertEqual(button['status_labels'][demo.STATES['config']], 'MY CONFIG')
        self.assertEqual(button['status_labels'][demo.STATES['fresh']], 'FRESH')
