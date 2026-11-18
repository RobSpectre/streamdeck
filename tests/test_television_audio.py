import copy
from contextlib import nullcontext
import unittest
from unittest.mock import Mock, patch

from tools import television_audio as tv
from tools.dial_controls import Dials


class TelevisionTests(unittest.TestCase):
    def setUp(self):
        self.current = [{'index': 100+i, 'client': str(200+i), 'mute': i != 0,
                         'volume': {'left': {'value': 32768}},
                         'properties': {'application.process.binary': 'chrome',
                                        'application.process.id': '42', 'object.serial': str(300+i)}}
                        for i in range(4)]
        self.slots = {str(i): {'stream': {'index': 100+i, 'client': str(200+i),
                                       'serial': str(300+i), 'process': [42, 'start', 'boot']},
                              'window': {'window': str(400+i), 'process': [41, 'start', 'boot']}}
                      for i in range(4)}
        for target, value in [('process_identity', lambda pid: [int(pid), 'start', 'boot']),
                              ('window_identity', lambda w: {'window': str(w), 'process': [41, 'start', 'boot']})]:
            patcher = patch.object(tv, target, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in [('streams', lambda: copy.deepcopy(self.current)),
                              ('load', lambda: copy.deepcopy(self.slots)), ('locked', nullcontext)]:
            patcher = patch.object(tv, target, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.writes = []

    def command(self, *args):
        self.writes.append(args)
        stream = next(s for s in self.current if str(s['index']) == args[2])
        if args[1] == 'set-sink-input-mute':
            stream['mute'] = args[3] == '1'
        return ''

    def test_solo_mutes_others_first_and_never_touches_unbound_chrome(self):
        self.current.append({**self.current[0], 'index': 999})
        with patch.object(tv, 'run', side_effect=self.command):
            tv.solo(2)
        self.assertEqual([call[2:] for call in self.writes],
                         [('100', '1'), ('101', '1'), ('103', '1'), ('102', '0')])
        self.assertEqual([s['mute'] for s in self.current], [True, True, False, True, False])

    def test_missing_reused_or_reowned_stream_refuses_without_writes(self):
        for mutation in ('missing', 'serial', 'client', 'owner'):
            with self.subTest(mutation=mutation):
                old = copy.deepcopy(self.current)
                if mutation == 'missing':
                    self.current.pop()
                elif mutation == 'serial':
                    self.current[3]['properties']['object.serial'] = '999'
                elif mutation == 'client':
                    self.current[3]['client'] = '999'
                else:
                    self.current[3]['properties']['application.process.id'] = '999'
                with patch.object(tv, 'run') as run:
                    with self.assertRaises(ValueError):
                        tv.solo(0)
                    run.assert_not_called()
                self.current = old

    def test_window_reuse_or_navigation_refuses(self):
        with patch.object(tv, 'window_identity', return_value={'window': '400', 'process': [99, 'new', 'boot']}), \
                patch.object(tv, 'run') as run:
            with self.assertRaises(ValueError):
                tv.solo(0)
        run.assert_not_called()

    def test_recheck_catches_disappearing_stream_before_unmute(self):
        def command(*args):
            self.command(*args)
            if len(self.writes) == 3:
                self.current[2]['properties']['object.serial'] = 'replacement'
        with patch.object(tv, 'run', side_effect=command):
            with self.assertRaises(ValueError):
                tv.solo(2)
        self.assertEqual(len(self.writes), 3)
        self.assertTrue(all(call[-1] == '1' for call in self.writes))

    def test_failed_mute_prevents_target_unmute(self):
        with patch.object(tv, 'run', return_value='') as run:
            with self.assertRaises(ValueError):
                tv.solo(2)
        self.assertEqual(run.call_count, 3)

    def test_rotation_clamps_and_preserves_mute(self):
        with patch.object(tv, 'run', side_effect=self.command):
            tv.rotate(2, 100)
            tv.rotate(2, -100)
        self.assertEqual([call[1:] for call in self.writes],
                         [('set-sink-input-volume', '102', '100.000%'),
                          ('set-sink-input-volume', '102', '0.000%')])
        self.assertTrue(self.current[2]['mute'])

    def test_invalid_slot_ticks_and_duplicate_bindings_refuse(self):
        with patch.object(tv, 'run') as run:
            for slot in [-1, 4, True, '1']:
                with self.assertRaises(ValueError):
                    tv.solo(slot)
            for ticks in [True, '2', 101]:
                with self.assertRaises(ValueError):
                    tv.rotate(0, ticks)
            self.slots['3'] = self.slots['2']
            with self.assertRaises(ValueError):
                tv.solo(0)
        run.assert_not_called()

    def test_snapshot_uses_real_volume_and_marks_only_missing_stream_unavailable(self):
        self.current.pop()
        result = tv.snapshot()
        self.assertEqual(result[0]['volume'], 50)
        self.assertFalse(result[0]['mute'])
        self.assertTrue(result[1]['mute'])
        self.assertIsNone(result[3])

    def test_bind_rejects_duplicate_and_non_chrome_stream(self):
        with self.assertRaises(ValueError):
            tv.bind(0, 102, 400)
        self.current[0]['properties']['application.process.binary'] = 'spotify'
        with self.assertRaises(ValueError):
            tv.bind(0, 100, 400)


class TelevisionDialTests(unittest.TestCase):
    def setUp(self):
        self.dials = Dials(Mock())
        self.settings = {'id': 'dial:spotify', 'kind': 'dial', 'control': 'spotify', 'title': 'SPOTIFY',
                         'television': {'control': 'television', 'slot': 1, 'title': tv.TITLES[1]}}

    def test_view_change_does_not_change_audio_and_preserves_end_dials(self):
        with patch.object(tv, 'solo') as solo, patch('tools.dial_controls.run') as run:
            self.dials.select_view('television')
            for control in ('pc_volume', 'mic_volume'):
                s = {'control': control}
                self.assertEqual(self.dials.effective(s), s)
            self.dials.select_view('studio')
        self.assertEqual(self.dials.effective(self.settings), self.settings)
        solo.assert_not_called()
        run.assert_not_called()

    def test_touch_and_press_solo_once_holds_and_studio_press_are_inert(self):
        with patch.object(tv, 'solo') as solo:
            self.dials.press(self.settings)
            self.dials.select_view('television')
            self.dials.tap(self.settings, hold=True)
            solo.assert_not_called()
            self.dials.press(self.settings)
            self.dials.tap(self.settings)
        self.assertEqual([c.args for c in solo.call_args_list], [(1,), (1,)])

    def test_snapshot_uses_single_tv_poll_and_keeps_original_context_id(self):
        self.dials.select_view('television')
        with patch.object(tv, 'snapshot', return_value={1: {'title': tv.TITLES[1], 'volume': 42, 'mute': False}}) as poll:
            value = self.dials.snapshot([self.settings])['dial:spotify']
        poll.assert_called_once()
        self.assertEqual(value['title'], tv.TITLES[1])
        self.assertEqual(value['value'], '42%')
        with patch.object(tv, 'snapshot', side_effect=OSError):
            value = self.dials.snapshot([self.settings])['dial:spotify']
        self.assertEqual(value['title'], tv.TITLES[1])
        self.assertEqual(value['detail'], 'REBIND TV AUDIO')


if __name__ == '__main__':
    unittest.main()
