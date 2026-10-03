import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tools.dial_controls import Dials, feedback
from tools import dial_desktop


class DialTests(unittest.TestCase):
    def test_pulse_tracks_default_and_clamps_without_unmuting(self):
        dials = Dials(Mock())
        device = {'name': 'speakers', 'volume': {'left': {'value': 65536}}, 'mute': True}
        replies = [json.dumps({'default_sink_name': 'speakers'}), json.dumps([device]), '']
        with patch('tools.dial_controls.run', side_effect=replies) as run:
            dials.rotate({'control': 'pc_volume'}, 4)
        self.assertEqual(run.call_args.args, ('pactl', 'set-sink-volume', 'speakers', '100.000%'))
        with patch('tools.dial_controls.run', side_effect=replies[:2]):
            self.assertEqual(dials.read({'control': 'pc_volume', 'title': 'PC'})['detail'], 'MUTED')

    def test_default_monitor_is_not_a_mic(self):
        dials = Dials(Mock())
        with patch('tools.dial_controls.run', side_effect=[
                json.dumps({'default_source_name': 'speakers.monitor'}),
                json.dumps([{'name': 'speakers.monitor'}])]):
            with self.assertRaises(ValueError):
                dials.rotate({'control': 'mic_volume'}, 1)

    def test_obs_uses_exact_input_and_decibels(self):
        obs = Mock()
        obs.get_scene_collection_list.return_value = SimpleNamespace(current_scene_collection_name='hack.party')
        obs.get_input_volume.return_value = SimpleNamespace(input_volume_db=-12)
        dials = Dials(lambda: obs)
        dials.rotate({'control': 'obs_volume', 'input': 'XAir'}, 3)
        obs.set_input_volume.assert_called_once_with('XAir', vol_db=-9)
        obs.get_scene_collection_list.return_value.current_scene_collection_name = 'Other'
        with self.assertRaises(ValueError):
            dials.rotate({'control': 'obs_volume', 'input': 'XAir'}, 1)
        self.assertEqual(obs.set_input_volume.call_count, 1)

    def test_failure_and_unknown_are_not_fake_meter_readings(self):
        dials = Dials(Mock())
        settings = {'id': 'spotify', 'control': 'spotify', 'title': 'SPOTIFY'}
        with patch('tools.dial_controls.run', side_effect=RuntimeError):
            result = dials.snapshot([settings])['spotify']
        self.assertEqual(result['value'], '—')
        self.assertEqual(result['detail'], 'UNAVAILABLE')
        self.assertEqual(feedback('FONT', None, detail='GNOME TERMINAL')['value'], '—')
        with self.assertRaises(ValueError):
            feedback('VOLUME', float('nan'))

    def test_invalid_ticks_cannot_dispatch(self):
        dials = Dials(Mock())
        with patch('tools.dial_controls.run') as run:
            for ticks in [True, 1.2, 101, '1']:
                with self.assertRaises(ValueError):
                    dials.rotate({'control': 'spotify'}, ticks)
            dials.rotate({'control': 'spotify'}, 0)
        run.assert_not_called()

    def test_terminal_targets_native_window_and_rechecks_focus(self):
        focus = ('123', {'WM_CLASS': ['Gnome-terminal'], '_GTK_UNIQUE_BUS_NAME': [':1.42'],
                         '_GTK_WINDOW_OBJECT_PATH': ['/org/gnome/Terminal/window/3']})
        with patch.object(dial_desktop, 'focused', return_value=focus), patch.object(dial_desktop, 'dbus_call') as call:
            dial_desktop.window_control('terminal_font', -1)
        self.assertEqual(call.call_args.args[:4], (':1.42', '/org/gnome/Terminal/window/3', 'org.gtk.Actions', 'Activate'))
        self.assertEqual(call.call_args.args[-1][0], 'zoom-out')
        with patch.object(dial_desktop, 'focused', side_effect=[focus, ('456', {})]), patch.object(dial_desktop, 'dbus_call') as call:
            with self.assertRaises(RuntimeError):
                dial_desktop.window_control('terminal_font', 1)
        call.assert_not_called()

    def test_unsupported_apps_receive_no_keys(self):
        with patch.object(dial_desktop, 'focused', return_value=('123', {'WM_CLASS': ['Unknown']})), patch.object(dial_desktop, 'command') as command:
            with self.assertRaises(ValueError):
                dial_desktop.window_control('window_zoom', 1)
        command.assert_not_called()

    def test_spotify_ambiguity_does_not_write_or_start_apps(self):
        with patch.object(dial_desktop, 'dbus_call', return_value=(['org.mpris.MediaPlayer2.spotify', 'org.mpris.MediaPlayer2.spotify.second'],)) as call:
            # Spotify imports GLib; use system Python for this one in desktop tests.
            try:
                import gi
            except ImportError:
                self.skipTest('System GI is outside the repository venv')
            with self.assertRaises(RuntimeError):
                dial_desktop.spotify(1)
        self.assertEqual(call.call_count, 1)

    def test_taps_toggle_bound_audio_targets_without_changing_volume(self):
        dials = Dials(Mock())
        for kind, command in [('pc_volume', 'set-sink-mute'), ('mic_volume', 'set-source-mute')]:
            with patch.object(dials, 'pulse_target', return_value=({'name': 'exact-device'}, 74)), patch('tools.dial_controls.run') as run:
                dials.tap({'control': kind})
            run.assert_called_once_with('pactl', command, 'exact-device', 'toggle')
        obs = Mock()
        obs.get_scene_collection_list.return_value = SimpleNamespace(current_scene_collection_name='hack.party')
        dials = Dials(lambda: obs)
        dials.tap({'control': 'obs_volume', 'input': 'XAir'})
        obs.toggle_input_mute.assert_called_once_with('XAir')
        obs.set_input_volume.assert_not_called()
        obs.get_scene_collection_list.return_value.current_scene_collection_name = 'other'
        with self.assertRaises(ValueError):
            dials.tap({'control': 'obs_volume', 'input': 'XAir'})
        self.assertEqual(obs.toggle_input_mute.call_count, 1)

    def test_spotify_tap_preserves_volume_and_mutes_only_spotify(self):
        dials = Dials(Mock())
        streams = [{'index': 17, 'mute': False, 'properties': {'application.process.binary': 'spotify', 'application.process.id': '42'}},
                   {'index': 18, 'mute': True, 'properties': {'application.process.binary': 'spotify', 'application.process.id': '42'}},
                   {'index': 19, 'mute': False, 'properties': {'application.process.binary': 'chrome', 'application.process.id': '43'}}]
        for muted, expected in [(False, '1'), (True, '0')]:
            streams[0]['mute'] = muted
            with patch('tools.dial_controls.run', side_effect=[json.dumps(streams), '[]', '', '']) as run:
                dials.tap({'control': 'spotify'})
            self.assertEqual([c.args for c in run.call_args_list[2:]],
                             [('pactl', 'set-sink-input-mute', '17', expected),
                              ('pactl', 'set-sink-input-mute', '18', expected)])
        streams[1]['properties']['application.process.id'] = '45'
        with patch('tools.dial_controls.run', side_effect=[json.dumps(streams), '[]']) as run:
            with self.assertRaises(ValueError):
                dials.tap({'control': 'spotify'})
        self.assertEqual(run.call_count, 2)
        with patch('tools.dial_controls.run', return_value='[]') as run:
            with self.assertRaises(ValueError):
                dials.tap({'control': 'spotify'})
        self.assertEqual(run.call_count, 2)

    def test_holds_and_non_audio_taps_do_nothing(self):
        dials = Dials(Mock())
        with patch('tools.dial_controls.run') as run:
            for kind in ['pc_volume', 'mic_volume', 'spotify', 'obs_volume']:
                dials.tap({'control': kind}, hold=True)
            for kind in ['terminal_font', 'window_zoom']:
                dials.tap({'control': kind})
        run.assert_not_called()
        dials.obs_client.assert_not_called()

    def test_spotify_readout_shows_actual_stream_mute(self):
        dials = Dials(Mock())
        with patch('tools.dial_controls.run', return_value='{"value": 63}'), patch.object(dials, 'spotify_streams', return_value=[{'mute': True}]):
            result = dials.read({'control': 'spotify', 'title': 'SPOTIFY'})
        self.assertEqual(result['value'], '0%')
        self.assertEqual(result['indicator'], 0)
        self.assertEqual(result['detail'], 'MUTED')

    def test_muted_meter_is_zero_and_background_is_red(self):
        import base64
        import io
        from PIL import Image
        for value, unit in [(63, '%'), (-9, 'dB')]:
            muted = feedback('TEST', value, unit, muted=True)
            active = feedback('TEST', value, unit)
            self.assertEqual(muted['indicator'], 0)
            self.assertEqual(muted['detail'], 'MUTED')
            self.assertGreater(active['indicator'], 0)
            self.assertEqual(active['value'], f'{value:.0f}{unit}')
            image = Image.open(io.BytesIO(base64.b64decode(muted['background'].split(',')[1])))
            self.assertEqual(image.size, (200, 100))
            self.assertEqual(image.getpixel((0, 0)), (165, 31, 50))
            self.assertNotEqual(muted['background'], active['background'])

    def test_the_battle_gap_dial_reads_and_writes_the_width(self):
        dials = Dials(Mock())
        settings = {'id': 'dial:f1_gap_limit', 'control': 'f1_gap_limit', 'title': 'BATTLE GAP'}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CACHE_HOME': directory}):
            reading = dials.read(settings)
            self.assertEqual(reading['title'], 'BATTLE GAP')
            self.assertEqual(reading['value'], '2.0s')
            self.assertEqual(reading['detail'], 'BATTLE WIDTH')
            self.assertAlmostEqual(reading['indicator']['value'], (2.0 - 0.5) / 4.5 * 100)
            self.assertTrue(reading['indicator']['enabled'])
            # A twist answers the strip immediately, and the stored value follows.
            stepped = dials.rotate(settings, 3)
            self.assertEqual(stepped['dial:f1_gap_limit']['value'], '2.3s')
            self.assertEqual(dials.read(settings)['value'], '2.3s')
            self.assertEqual(dials.rotate(settings, -100)['dial:f1_gap_limit']['value'], '0.5s')
            self.assertEqual(dials.rotate(settings, 100)['dial:f1_gap_limit']['value'], '5.0s')
            self.assertFalse(os.path.exists(os.path.join(directory, 'opendeck-agents', 'f1-battles', 'gap-limit.tmp')))

    def test_the_battle_gap_dial_reads_the_default_when_nothing_is_stored(self):
        dials = Dials(Mock())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CACHE_HOME': directory}):
            self.assertEqual(dials.read({'control': 'f1_gap_limit', 'title': 'BATTLE GAP'})['value'], '2.0s')

    def test_hidden_battle_dial_is_blank_and_cannot_change_the_preference(self):
        dials = Dials(Mock(), battle_visible=lambda: False)
        settings = {'id': 'gap', 'control': 'f1_gap_limit', 'title': 'BATTLE GAP'}
        with patch('tools.dial_controls.set_gap_limit') as write:
            result = dials.read(settings)
            self.assertEqual([result[k] for k in ('title', 'value', 'detail')], ['', '', ''])
            self.assertEqual(result['indicator'], {'value': 0, 'enabled': False})
            self.assertIsNone(dials.rotate(settings, 3))
            write.assert_not_called()

    def test_the_battle_gap_dial_is_not_an_audio_target(self):
        dials = Dials(Mock())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CACHE_HOME': directory}), \
                patch('tools.dial_controls.run') as run:
            dials.tap({'control': 'f1_gap_limit', 'title': 'BATTLE GAP'})
            dials.tap({'control': 'f1_gap_limit', 'title': 'BATTLE GAP'}, hold=True)
        run.assert_not_called()

    def test_native_pipewire_spotify_identity_is_resolved_from_client(self):
        streams = [{'index': 4718, 'client': '4717', 'mute': False,
                    'properties': {'application.name': 'Spotify', 'node.name': 'spotify'}},
                   {'index': 5000, 'client': '4999', 'mute': False,
                    'properties': {'application.name': 'Spotify', 'node.name': 'spotify'}}]
        clients = [{'index': 4717, 'properties': {'application.process.binary': 'spotify',
                                                'pipewire.sec.pid': '383239'}},
                   {'index': 4999, 'properties': {'application.process.binary': 'chrome',
                                                'pipewire.sec.pid': '222'}}]
        dials = Dials(Mock())
        with patch('tools.dial_controls.run', side_effect=[json.dumps(streams), json.dumps(clients), '']) as run:
            dials.tap({'control': 'spotify'})
        self.assertEqual(run.call_args.args, ('pactl', 'set-sink-input-mute', '4718', '1'))
        self.assertEqual(run.call_count, 3)
        streams[0]['mute'] = True
        with patch('tools.dial_controls.run', side_effect=['{"value": 63}', json.dumps(streams), json.dumps(clients)]):
            self.assertEqual(dials.read({'control': 'spotify', 'title': 'SPOTIFY'})['detail'], 'MUTED')
