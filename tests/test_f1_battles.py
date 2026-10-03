import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import f1_battles as fb


def line(position, interval=None, catching=False, **flags):
    value = {'Position': str(position), 'IntervalToPositionAhead': {'Value': interval, 'Catching': catching}}
    value.update(flags)
    return value


DRIVERS = {
    '1': {'Tla': 'VER', 'TeamColour': '4781D7'},
    '4': {'Tla': 'NOR', 'TeamColour': 'F47600'},
    '44': {'Tla': 'HAM', 'TeamColour': 'E8002D'},
    '16': {'Tla': 'LEC', 'TeamColour': 'E8002D'},
}


class GapTests(unittest.TestCase):
    def test_only_a_finite_number_is_a_gap(self):
        self.assertEqual(fb.parse_gap('+0.979'), 0.979)
        self.assertEqual(fb.parse_gap(' 1.5 '), 1.5)
        self.assertEqual(fb.parse_gap('0.25'), 0.25)
        # Lapped traffic and unset intervals are unknown, not zero.
        self.assertIsNone(fb.parse_gap('+1 LAP'))
        self.assertIsNone(fb.parse_gap(''))
        self.assertIsNone(fb.parse_gap(None))
        self.assertIsNone(fb.parse_gap('-0.500'))
        self.assertIsNone(fb.parse_gap('inf'))

    def test_positions_only_parse_from_numbers(self):
        self.assertEqual(fb.parse_position('6'), 6)
        self.assertIsNone(fb.parse_position(None))
        self.assertIsNone(fb.parse_position('R'))

    def test_the_gap_is_shown_in_hundredths(self):
        self.assertEqual(fb.gap_text(0.979), '+0.98')
        self.assertEqual(fb.gap_text(1.0), '+1.00')

    def test_the_gap_colour_scale(self):
        # A second or more is comfortable, under a second is a fight, under five
        # tenths is about to be resolved.
        self.assertEqual(fb.gap_colour('+2.00'), fb.GREEN)
        self.assertEqual(fb.gap_colour('+1.00'), fb.GREEN)
        self.assertEqual(fb.gap_colour('+0.99'), fb.YELLOW)
        self.assertEqual(fb.gap_colour('+0.50'), fb.YELLOW)
        self.assertEqual(fb.gap_colour('+0.49'), fb.RED)
        self.assertEqual(fb.gap_colour('+1 LAP'), fb.IDLE)


class GapLimitTests(unittest.TestCase):
    def test_the_dial_default_is_two_seconds(self):
        self.assertEqual(fb.GAP_LIMIT, 2.0)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(fb.gap_limit(Path(directory)/'unset'), 2.0)

    def test_the_setting_round_trips_and_snaps_to_whole_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'gap-limit'
            self.assertEqual(fb.set_gap_limit(2.34, path), 2.3)
            self.assertEqual(fb.gap_limit(path), 2.3)
            self.assertEqual(path.read_text().strip(), '2.3')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_the_setting_is_clamped_to_the_dials_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'gap-limit'
            self.assertEqual(fb.set_gap_limit(-4, path), fb.GAP_LIMIT_MIN)
            self.assertEqual(fb.set_gap_limit(99, path), fb.GAP_LIMIT_MAX)
            with self.assertRaises(ValueError):
                fb.set_gap_limit(float('nan'), path)

    def test_an_unreadable_or_out_of_range_file_falls_back_to_the_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'gap-limit'
            path.write_text('not a number\n')
            self.assertEqual(fb.gap_limit(path), fb.GAP_LIMIT)
            path.write_text('90\n')
            self.assertEqual(fb.gap_limit(path), fb.GAP_LIMIT)

    def test_the_keys_use_the_dialled_width(self):
        timing = {'Lines': {'1': line(1, None, False), '4': line(2, '+1.800', True)}}
        self.assertEqual(len(fb.battles(timing, DRIVERS)), 1)
        self.assertEqual(fb.battles(timing, DRIVERS, gap=fb.GAP_LIMIT_MIN), [])
        wide = {'Lines': {'1': line(1, None, False), '4': line(2, '+4.400', True)}}
        self.assertEqual(fb.battles(wide, DRIVERS), [])
        self.assertEqual(len(fb.battles(wide, DRIVERS, gap=5.0)), 1)


def frame(lap, gap=1.200, catching=True, ahead=('1', 1), behind=('4', 2), pit=False):
    """One timing frame: two cars, the trailing one carrying the interval."""
    return {'TimingData': {'Lines': {
        ahead[0]: line(ahead[1], None, False, NumberOfLaps=lap),
        behind[0]: line(behind[1], f'+{gap:.3f}', catching, NumberOfLaps=lap, InPit=pit)}},
        'DriverList': DRIVERS, 'SessionInfo': {'Type': 'Race', 'Key': 1},
        'SessionStatus': {'Status': 'Started'}}


def closing(timing, drivers, **kwargs):
    """The pairs the deck would call a battle at this instant."""
    return [pair for pair in fb.battle_pairs(timing, drivers, **kwargs) if pair['closing']]


class PairTests(unittest.TestCase):
    def test_a_pair_needs_both_the_gap_and_the_catching_flag(self):
        # The interval belongs to the trailing car: NOR is 1.9s behind VER.
        timing = {'Lines': {'1': line(1, None, False), '4': line(2, '+1.900', True),
                            '44': line(3, '+2.500', True), '16': line(4, '+2.400', True)}}
        # VER/NOR is inside two seconds; HAM/LEC is 2.4s and not a battle.
        self.assertEqual([(b['ahead']['tla'], b['behind']['tla']) for b in closing(timing, DRIVERS)],
                         [('VER', 'NOR')])
        # A car inside the window the feed does not flag as closing is not a battle.
        timing['Lines']['4']['IntervalToPositionAhead'] = {'Value': '+1.900', 'Catching': False}
        self.assertEqual(closing(timing, DRIVERS), [])

    def test_pairs_are_ranked_from_the_front_of_the_field(self):
        # VER leads NOR by 1.8s and HAM leads LEC by 0.4s: the tighter fight is
        # behind, and the deck still puts the fight for the lead on the top row.
        timing = {'Lines': {'1': line(1, None, False), '4': line(2, '+1.800', True),
                            '44': line(3, '+1.500', True), '16': line(4, '+0.400', True)}}
        self.assertEqual([(p['ahead']['tla'], p['behind']['tla']) for p in closing(timing, DRIVERS)],
                         [('VER', 'NOR'), ('NOR', 'HAM'), ('HAM', 'LEC')])
        self.assertEqual([round(p['gap'], 2) for p in closing(timing, DRIVERS)], [1.8, 1.5, 0.4])

    def test_only_the_four_front_places_are_kept(self):
        timing = {'Lines': {str(i): line(i, f'+{0.5 + i/10:.3f}', True) for i in range(1, 7)}}
        drivers = {str(i): {'Tla': f'D{i}', 'TeamColour': 'FFFFFF'} for i in range(1, 7)}
        found = fb.battles(timing, drivers)
        self.assertEqual(len(found), fb.BATTLE_LIMIT)
        self.assertEqual([p['ahead']['position'] for p in found], [1, 2, 3, 4])
        # Gaps still read from the trailing car: (1,2) carries car 2's interval.
        self.assertEqual([round(p['gap'], 3) for p in found], [0.7, 0.8, 0.9, 1.0])
        self.assertEqual(fb.gap_text(found[0]['gap']), '+0.70')

    def test_a_pit_stop_ends_a_pair_immediately(self):
        # A car in the pit is not on track, so the pair is gone rather than held:
        # the hold covers the flag and the gap flickering, not a fight that ended.
        timing = {'Lines': {'1': line(1, None, False), '4': line(2, '+1.100', True, InPit=True)}}
        self.assertEqual(fb.battle_pairs(timing, DRIVERS), [])
        self.assertEqual(fb.battles(timing, DRIVERS), [])

    def test_non_consecutive_positions_are_not_a_pair(self):
        # A car whose position is missing would otherwise pair cars a lap apart.
        timing = {'Lines': {'1': line(1, '+0.400', True), '4': line(3, '+0.300', True)}}
        self.assertEqual(fb.battles(timing, DRIVERS), [])

    def test_cars_off_track_are_not_battling(self):
        timing = {'Lines': {'1': line(1, '+0.400', True), '4': line(2, '+0.300', True, InPit=True),
                            '44': line(3, '+0.300', True, Retired=True), '16': line(4, '+0.300', True)}}
        self.assertEqual(fb.battles(timing, DRIVERS), [])

    def test_unreadable_rows_are_dropped_rather_than_guessed(self):
        timing = {'Lines': {'1': line(1, 'LAP 4', False), '4': line(2, None, True),
                            '44': line(3, '+0.300', True), '16': line(4, '+0.200', True),
                            '63': line(5, '+0.100', True)}}
        # RUS has no DriverList entry, so no LEC/RUS pair exists even though its
        # interval reads. VER's '+1 LAP' is not a gap, which only disqualifies it
        # as the closing car, not as the car NOR is fighting behind.
        found = fb.battles(timing, DRIVERS)
        self.assertEqual([(b['ahead']['tla'], b['behind']['tla']) for b in found],
                         [('NOR', 'HAM'), ('HAM', 'LEC')])

    def test_the_leader_is_still_the_car_ahead_of_the_first_battle(self):
        # The leader carries no interval at all in some frames; dropping it would
        # silently lose a fight for the lead.
        timing = {'Lines': {'1': {'Position': '1'}, '4': line(2, '+0.250', True)}}
        found = fb.battles(timing, DRIVERS)
        self.assertEqual([(b['ahead']['tla'], b['behind']['tla'], fb.gap_text(b['gap'])) for b in found],
                         [('VER', 'NOR', '+0.25')])

    def test_empty_and_missing_topics_yield_no_battles(self):
        self.assertEqual(fb.battles({}, {}), [])
        self.assertEqual(fb.battles(None, None), [])
        self.assertEqual(fb.battle_pairs({}, {}), [])


class LapTests(unittest.TestCase):
    def test_the_lap_clock_is_the_leaders(self):
        # The leader's count, not either car's in a pair, so an overtake between
        # two cars cannot restart their fight's age.
        timing = {'Lines': {'1': {'NumberOfLaps': 30}, '4': {'NumberOfLaps': 29},
                            '16': {'NumberOfLaps': '12'}}}
        self.assertEqual(fb.session_lap(timing), 30)
        self.assertIsNone(fb.session_lap({'Lines': {}}))
        self.assertIsNone(fb.session_lap({}))
        self.assertIsNone(fb.session_lap(None))

    def test_a_pair_keeps_its_key_when_the_two_cars_swap(self):
        one = {'ahead': {'number': '1'}, 'behind': {'number': '4'}}
        other = {'ahead': {'number': '4'}, 'behind': {'number': '1'}}
        self.assertEqual(fb.pair_key(one), fb.pair_key(other))


class HoldTests(unittest.TestCase):
    def setUp(self):
        probe = mock.patch.object(fb, 'api_available', return_value=True)
        probe.start()
        self.addCleanup(probe.stop)

    def feed(self, *frames):
        feed = fb.BattleFeed(ttl=0)
        fetch = mock.patch.object(fb, 'fetch', side_effect=list(frames))
        self.addCleanup(fetch.stop)
        fetch.start()
        return feed

    def test_a_battle_stands_for_two_laps_after_it_stops_closing(self):
        # Closing on lap 10, and then neither the flag nor the gap says so again.
        feed = self.feed(frame(10, gap=1.200), frame(10, gap=3.400, catching=False),
                         frame(11, gap=3.400, catching=False), frame(12, gap=3.400, catching=False))
        self.assertEqual(len(feed.value()[0]), 1, 'closing now')
        self.assertEqual(len(feed.value()[0]), 1, 'still up, same lap')
        self.assertEqual(len(feed.value()[0]), 1, 'still up a lap later')
        self.assertEqual(feed.value()[0], [], 'two laps without closing is the end of it')

    def test_a_held_battle_shows_its_live_gap_not_the_one_it_was_found_with(self):
        feed = self.feed(frame(10, gap=1.200), frame(10, gap=3.400, catching=False))
        feed.value()
        rows, available = feed.value()
        self.assertTrue(available)
        self.assertEqual(fb.gap_text(rows[0]['gap']), '+3.40')
        self.assertEqual(fb.headline(fb.slot_value(rows, True, 1)), ('+3.40', fb.GREEN))

    def test_an_overtake_between_the_two_cars_does_not_restart_the_hold(self):
        feed = self.feed(frame(10, gap=0.400),
                         frame(10, gap=3.400, catching=False, ahead=('4', 1), behind=('1', 2)),
                         frame(11, gap=3.400, catching=False, ahead=('4', 1), behind=('1', 2)))
        feed.value()
        rows, _ = feed.value()
        self.assertEqual(len(rows), 1, 'the same fight, now the other way round')
        self.assertEqual(rows[0]['ahead']['tla'], 'NOR')
        self.assertEqual(len(feed.value()[0]), 1, 'and still up on the next lap')

    def test_a_pit_stop_ends_the_hold_at_once(self):
        feed = self.feed(frame(10, gap=1.200), frame(10, gap=3.400, catching=False, pit=True))
        self.assertEqual(len(feed.value()[0]), 1)
        self.assertEqual(feed.value()[0], [])

    def test_a_new_session_does_not_revive_an_old_battle(self):
        # A lap count that has gone backwards is a fresh session, not an age.
        feed = self.feed(frame(30, gap=1.200), frame(1, gap=3.400, catching=False))
        self.assertEqual(len(feed.value()[0]), 1)
        self.assertEqual(feed.value()[0], [])

    def test_an_unmeasurable_lap_switches_the_hold_off(self):
        feed = self.feed(frame(None, gap=1.200), frame(None, gap=3.400, catching=False))
        self.assertEqual(len(feed.value()[0]), 1)
        self.assertEqual(feed.value()[0], [])

    def test_the_hold_never_grows_the_deck_past_four_rows(self):
        lines = {str(i): line(i, f'+1.0{i:02d}', True, NumberOfLaps=7) for i in range(1, 8)}
        drivers = {str(i): {'Tla': f'D{i}', 'TeamColour': 'FFFFFF'} for i in range(1, 8)}
        feed = self.feed({'TimingData': {'Lines': lines}, 'DriverList': drivers,
                          'SessionInfo': {'Type': 'Race'}, 'SessionStatus': {'Status': 'Started'}})
        rows, _ = feed.value()
        self.assertEqual([row['ahead']['position'] for row in rows], [1, 2, 3, 4])


class SlotTests(unittest.TestCase):
    ROWS = [{'ahead': {'tla': 'VER', 'colour': '#4781D7', 'position': 3},
             'behind': {'tla': 'NOR', 'colour': '#F47600', 'position': 4},
             'gap': 1.17}]

    def test_leader_is_the_left_key_and_trailer_the_right(self):
        lead = fb.slot_value(self.ROWS, True, 0)
        trail = fb.slot_value(self.ROWS, True, 1)
        self.assertEqual(lead[:4], ('battle', 'VER', '+1.17', 'lead'))
        self.assertEqual(trail[:4], ('battle', 'NOR', '+1.17', 'trail'))
        self.assertEqual(lead[4], '#4781D7')

    def test_the_leader_headlines_the_position_and_the_trailer_the_gap(self):
        lead = fb.headline(fb.slot_value(self.ROWS, True, 0))
        trail = fb.headline(fb.slot_value(self.ROWS, True, 1))
        # (big text, its colour)
        self.assertEqual(lead, ('P3', '#ffffff'))
        self.assertEqual(trail, ('+1.17', fb.GREEN))
        close = fb.headline(('battle', 'NOR', '+0.30', 'trail', '#F47600', 4))
        self.assertEqual(close, ('+0.30', fb.RED))

    def test_slots_past_the_battles_are_empty_and_a_dead_feed_is_unavailable(self):
        self.assertEqual(fb.slot_value(self.ROWS, True, 2)[0], 'empty')
        self.assertEqual(fb.slot_value(self.ROWS, True, 7)[0], 'empty')
        self.assertEqual(fb.slot_value([], False, 0)[0], 'unavailable')


class FeedTests(unittest.TestCase):
    def setUp(self):
        probe = mock.patch.object(fb, 'api_available', return_value=True)
        probe.start()
        self.addCleanup(probe.stop)

    def test_the_read_is_cached_for_its_ttl(self):
        feed = fb.BattleFeed(ttl=1.0)
        with mock.patch.object(fb, 'fetch', return_value={'TimingData': {}, 'DriverList': {}}) as fetch:
            self.assertEqual(feed.value(now=10.0), ([], True))
            feed.value(now=10.5)
            self.assertEqual(fetch.call_count, 1)
            feed.value(now=11.5)
            self.assertEqual(fetch.call_count, 2)

    def test_a_failed_read_reports_unavailable_rather_than_stale_battles(self):
        feed = fb.BattleFeed(ttl=1.0)
        with mock.patch.object(fb, 'fetch', side_effect=OSError('no server')):
            self.assertEqual(feed.value(now=1.0), ([], False))

    def test_a_press_reads_the_cache_the_keys_were_drawn_from(self):
        feed = fb.BattleFeed(ttl=1.0)
        with mock.patch.object(fb, 'fetch',
                                        return_value={'TimingData': {'Lines': {}}, 'DriverList': {}}) as fetch:
            feed.value(now=10.0)
            feed.value(now=99.0, refresh=False)
            self.assertEqual(fetch.call_count, 1)

    def test_offline_probe_skips_timing_and_backs_off(self):
        feed = fb.BattleFeed()
        with mock.patch.object(fb, 'api_available', return_value=False) as probe, mock.patch.object(fb, 'fetch') as fetch:
            feed.value(now=10)
            feed.value(now=11)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(feed.slot(0)[0], 'hidden')
            feed.value(now=15)
            self.assertEqual(probe.call_count, 2)
            fetch.assert_not_called()

    def test_pause_clears_cached_actions_and_resumes_with_a_fresh_read(self):
        feed = fb.BattleFeed()
        with mock.patch.object(fb, 'fetch', return_value=frame(10)) as fetch:
            feed.value(now=10)
            self.assertEqual(feed.slot(0)[1], 'VER')
            feed.pause()
            self.assertEqual(feed.slot(0)[0], 'hidden')
            self.assertEqual(feed.seen, {})
            feed.value(now=10.1)
            self.assertEqual(fetch.call_count, 2)

    def test_session_identity_clears_held_fights_even_when_laps_increase(self):
        feed = fb.BattleFeed(ttl=0)
        next_session = frame(30, catching=False)
        next_session['SessionInfo']['Key'] = 2
        with mock.patch.object(fb, 'fetch', side_effect=[frame(10), next_session]):
            self.assertEqual(len(feed.value()[0]), 1)
            self.assertEqual(feed.value()[0], [])

    def test_practice_and_session_end_clear_race_targets(self):
        for change in ('Practice', 'Ends'):
            state = frame(11)
            if change == 'Practice':
                state['SessionInfo']['Type'] = change
            else:
                state['SessionStatus']['Status'] = change
            feed = fb.BattleFeed(ttl=0)
            with mock.patch.object(fb, 'fetch', side_effect=[frame(10), state]):
                feed.value()
                feed.value()
            self.assertEqual(feed.slot(0)[0], 'hidden')
            self.assertEqual(feed.seen, {})

    def test_failed_api_backs_off_then_recovers_without_stale_actions(self):
        feed = fb.BattleFeed()
        with mock.patch.object(fb, 'fetch', side_effect=[frame(10), OSError('offline'), frame(11)]) as fetch:
            feed.value(now=10)
            self.assertEqual(feed.slot(0)[1], 'VER')
            feed.value(now=11)
            self.assertEqual(feed.slot(0)[0], 'hidden')
            feed.value(now=12)
            self.assertEqual(fetch.call_count, 2)
            feed.value(now=16)
            self.assertEqual(feed.slot(0)[1], 'VER')

    def test_graphql_errors_and_missing_state_are_unavailable(self):
        for payload in ({'errors': [{'message': 'schema changed'}]}, {'data': {'liveTimingState': None}}):
            response = mock.Mock()
            response.json.return_value = payload
            with mock.patch.object(fb.requests, 'post', return_value=response):
                with self.assertRaises(ValueError):
                    fb.fetch()

    def test_track_status_uses_the_same_read_and_clears_on_failure(self):
        state = frame(10)
        state['TrackStatus'] = {'Status': '5'}
        feed = fb.BattleFeed(ttl=0)
        with mock.patch.object(fb, 'fetch', side_effect=[state, OSError('offline')]) as fetch:
            feed.value()
            self.assertEqual(feed.track_status, 'red')
            self.assertEqual(fetch.call_count, 1)
            feed.value()
            self.assertIsNone(feed.track_status)


class SessionTests(unittest.TestCase):
    def test_only_known_competitive_sessions_show_controls(self):
        for kind, expected in [('Race', 'race'), ('Qualifying', 'qualifying'),
                               ('Practice', 'hidden'), ('Testing', 'hidden'), (None, 'hidden')]:
            for name in ('Sprint', 'Sprint Qualifying', 'Qualifying'):
                state = {'SessionInfo': {'Type': kind, 'Name': name}, 'SessionStatus': {'Status': 'Started'}}
                self.assertEqual(fb.session_mode(state), expected)
        self.assertEqual(fb.session_mode({}), 'hidden')
        for status in ('Inactive', 'Ends', 'Finalised', None):
            self.assertEqual(fb.session_mode({'SessionInfo': {'Type': 'Race'},
                                              'SessionStatus': {'Status': status}}), 'hidden')

    def test_qualifying_uses_individual_keys_and_hides_the_gap(self):
        state = frame(10)
        state['SessionInfo']['Type'] = 'Qualifying'
        for row in state['TimingData']['Lines'].values():
            row.update(Status=64, InPit=False, PitOut=False, Stopped=False, Retired=False)
        feed = fb.BattleFeed()
        with mock.patch.object(fb, 'api_available', return_value=True), mock.patch.object(fb, 'fetch', return_value=state):
            rows, _ = feed.value()
        self.assertEqual([car['tla'] for car in rows], ['VER', 'NOR'])
        self.assertEqual(feed.slot(0)[0:2], ('flying', 'VER'))
        self.assertEqual(feed.slot(1)[0:2], ('flying', 'NOR'))
        self.assertEqual(feed.slot(2)[0], 'no_flyer')
        self.assertEqual(feed.mode, 'qualifying')

    def test_flyers_require_explicit_flags_and_reject_outlaps(self):
        clear = dict(Position='1', Status=64, InPit=False, PitOut=False, Stopped=False, Retired=False)
        for changes in ({'Status': 576}, {'Status': 80}, {'Status': 96}, {'Status': 66},
                        {'Status': 68}, {'Status': None}, {'Outlap': True}, {'InPit': True},
                        {'Stopped': True}, {'Retired': True}, {'PitOut': True}, {'KnockedOut': True}):
            self.assertEqual(fb.flying_laps({'Lines': {'1': {**clear, **changes}}}, DRIVERS), [])
        missing = clear.copy()
        missing.pop('PitOut')
        self.assertEqual(fb.flying_laps({'Lines': {'1': missing}}, DRIVERS), [])
        self.assertEqual(len(fb.flying_laps({'Lines': {'1': clear}}, DRIVERS)), 1)

    def test_qualifying_order_is_deterministic_and_limited_to_eight(self):
        cars = [{'position': p, 'number': str(p)} for p in reversed(range(1, 12))]
        self.assertEqual([c['position'] for c in fb.qualifying_order(cars)], list(range(1, 9)))

    def test_top_four_teams_take_priority_over_faster_other_teams(self):
        cars = [{'position': p, 'number': str(p), 'team': team} for p, team in enumerate(
            ['Williams', 'Alpine', 'McLaren', 'Ferrari', 'Mercedes', 'Red Bull Racing',
             'McLaren', 'Ferrari', 'Mercedes', 'Red Bull Racing'], start=1)]
        self.assertEqual([c['position'] for c in fb.qualifying_order(cars)], list(range(3, 11)))

    def test_hidden_keys_are_black_even_under_a_flag(self):
        import base64
        import io
        from PIL import Image
        image = Image.open(io.BytesIO(base64.b64decode(fb.render(('hidden', '', '', '', fb.IDLE, ''), 'red').split(',')[1])))
        self.assertEqual(image.getextrema(), ((0, 0), (0, 0), (0, 0)))
        self.assertTrue(fb.render(('flying', 'VER', '', '', '#4781D7', 1)).startswith('data:image/png'))


class QualifyingTimerTests(unittest.TestCase):
    ORIGIN = 1700000000000

    def clock(self, **changes):
        return dict(paused=False, trackTime=str(self.ORIGIN + 60000),
                    liveTimingStartTime=str(self.ORIGIN), systemTime='100000', speed=1, **changes)

    def test_replay_timer_extrapolates_the_native_clock_anchor(self):
        self.assertEqual(fb.current_lap_seconds({'NumberOfLapsTs': 45000}, self.clock(), now=102), 17)

    def test_live_lap_starts_use_epoch_timestamps(self):
        self.assertEqual(fb.current_lap_seconds({'NumberOfLapsTs': self.ORIGIN + 45000}, self.clock(), now=102), 17)

    def test_pause_and_replay_speed_follow_native_clock(self):
        clock = self.clock()
        clock['paused'] = True
        self.assertEqual(fb.current_lap_seconds({'NumberOfLapsTs': 45000}, clock, now=500), 15)
        clock.update(paused=False, speed=2)
        self.assertEqual(fb.current_lap_seconds({'NumberOfLapsTs': 45000}, clock, now=102), 19)

    def test_new_lap_resets_and_a_seek_before_the_lap_refuses_stale_time(self):
        self.assertEqual(fb.current_lap_seconds({'NumberOfLapsTs': 60000}, self.clock(), now=100), 0)
        clock = self.clock()
        clock['trackTime'] = str(self.ORIGIN + 20000)
        self.assertIsNone(fb.current_lap_seconds({'NumberOfLapsTs': 45000}, clock, now=100))

    def test_missing_invalid_or_future_clock_data_is_unavailable(self):
        self.assertIsNone(fb.current_lap_seconds({}, self.clock(), now=100))
        self.assertIsNone(fb.current_lap_seconds({'NumberOfLapsTs': 45000}, None, now=100))
        self.assertIsNone(fb.current_lap_seconds({'NumberOfLapsTs': True}, self.clock(), now=100))
        for field, bad in [('speed', None), ('speed', -1), ('paused', None), ('trackTime', 'nan'),
                           ('systemTime', 'inf'), ('liveTimingStartTime', {})]:
            clock = self.clock()
            clock[field] = bad
            self.assertIsNone(fb.current_lap_seconds({'NumberOfLapsTs': 45000}, clock, now=100))
        self.assertIsNone(fb.current_lap_seconds({'NumberOfLapsTs': 45000}, self.clock(), now=99))

    def test_timer_format_uses_observed_tenths_and_minute_carry(self):
        for seconds, text in [(0, '0:00.0'), (59.999, '0:59.9'), (60, '1:00.0'),
                               (96.758, '1:36.7'), (None, '—'), (float('nan'), '—')]:
            self.assertEqual(fb.lap_time_text(seconds), text)

    def sector(self, *statuses):
        return {'Segments': [{'Status': status} for status in statuses]}

    def test_colour_follows_latest_reported_mini_sector_not_any_earlier_best(self):
        for status, colour in [(2048, fb.YELLOW), (2049, fb.GREEN), (2051, fb.PURPLE)]:
            self.assertEqual(fb.lap_colour({'Sectors': [self.sector(2051, status, 0)]}), colour)

    def test_future_and_previous_lap_sectors_do_not_supply_a_colour(self):
        line = {'Sectors': [self.sector(2049, 0), self.sector(2051, 2051)]}
        self.assertEqual(fb.lap_colour(line), fb.GREEN)
        line['Sectors'][0] = self.sector(0, 0)
        self.assertEqual(fb.lap_colour(line), fb.IDLE)

    def test_native_numeric_object_sectors_and_segments_are_sorted(self):
        line = {'Sectors': {'1': self.sector(2051, 0),
                            '0': {'Segments': {'1': {'Status': 2048}, '0': {'Status': 2049}}}}}
        self.assertEqual(fb.lap_colour(line), fb.PURPLE)

    def test_unknown_or_non_timed_segments_have_no_best_colour(self):
        for status in (2064, 2052, 2068, None, '2049', True):
            self.assertEqual(fb.lap_colour({'Sectors': [self.sector(2049, status)]}), fb.IDLE)
        self.assertEqual(fb.lap_colour({}), fb.IDLE)

    def test_flyer_slot_carries_timer_and_colour_into_render_and_cache(self):
        line = dict(Status=64, Position='1', InPit=False, PitOut=False, Stopped=False, Retired=False,
                    NumberOfLapsTs=45000, Sectors=[self.sector(2049, 2051, 0)])
        feed = fb.BattleFeed()
        feed.mode, feed.available = 'qualifying', True
        feed.rows = fb.flying_laps({'Lines': {'1': line}}, DRIVERS, self.clock(), now=100)
        self.assertEqual(feed.slot(0)[2:4], ('0:15.0', fb.PURPLE))
        self.assertEqual(fb.headline(feed.slot(0)), ('0:15.0', fb.PURPLE))
        before = fb.render(feed.slot(0))
        feed.rows[0]['lap_time'] = '0:16.0'
        self.assertNotEqual(before, fb.render(feed.slot(0)))
        feed.rows = fb.flying_laps({'Lines': {'1': line}}, DRIVERS)
        self.assertEqual(fb.headline(feed.slot(0)), ('—', fb.IDLE))

    def test_shared_fetch_reads_native_speed_only_in_qualifying(self):
        for kind, expected in [('Race', 0), ('Qualifying', 1), ('Practice', 0)]:
            response = mock.Mock()
            response.json.return_value = {'data': {'liveTimingState': {
                'SessionInfo': {'Type': kind}, 'SessionStatus': {'Status': 'Started'}}}}
            clock = mock.Mock()
            clock.json.return_value = self.clock()
            with mock.patch.object(fb.requests, 'post', return_value=response), \
                    mock.patch.object(fb.requests, 'get', return_value=clock) as get:
                state = fb.fetch()
            self.assertEqual(get.call_count, expected)
            if expected:
                self.assertEqual(state['_clock']['speed'], 1)

    def test_clock_failure_keeps_driver_selection_but_timer_is_unavailable(self):
        response = mock.Mock()
        response.json.return_value = {'data': {'liveTimingState': {
            'SessionInfo': {'Type': 'Qualifying'}, 'SessionStatus': {'Status': 'Started'}}}}
        with mock.patch.object(fb.requests, 'post', return_value=response), \
                mock.patch.object(fb.requests, 'get', side_effect=fb.requests.ConnectionError):
            self.assertIsNone(fb.fetch()['_clock'])


class RenderTests(unittest.TestCase):
    def test_a_battle_key_draws_a_png_data_uri(self):
        value = fb.slot_value([{'ahead': {'tla': 'VER', 'colour': '#4781D7', 'position': 3},
                                'behind': {'tla': 'NOR', 'colour': '#F47600', 'position': 4},
                                'gap': 1.17}], True, 0)
        self.assertTrue(fb.render(value).startswith('data:image/png;base64,'))
        self.assertTrue(fb.render(('empty', '', '', '', fb.IDLE, '')).startswith('data:image/png;base64,'))
        self.assertTrue(fb.render(('unavailable', '', '', '', fb.IDLE, '')).startswith('data:image/png;base64,'))

    def test_a_driver_without_a_headshot_still_renders(self):
        # There is no TSU.png in the 2026 asset set; the key must still draw.
        self.assertIsNone(fb.headshot('ZZZ'))
        value = fb.slot_value([{'ahead': {'tla': 'ZZZ', 'colour': '#1868DB', 'position': 9},
                                'behind': {'tla': 'NOR', 'colour': '#F47600', 'position': 10},
                                'gap': 0.8}], True, 0)
        self.assertTrue(fb.render(value).startswith('data:image/png;base64,'))

    def test_an_unreadable_position_still_draws_a_card(self):
        value = ('battle', 'VER', '+0.90', 'lead', '#4781D7', '')
        self.assertEqual(fb.headline(value)[0], '—')
        self.assertTrue(fb.render(value).startswith('data:image/png;base64,'))


class PlayerTests(unittest.TestCase):
    class Player:
        def __init__(self, id, title, tla, fullscreen=False):
            self.id, self.title, self.fullscreen = id, title, fullscreen
            self.driver_data = {'tla': tla} if tla else None
            self.calls = []
            self.set_fullscreen = mock.Mock(side_effect=self._fullscreen)
            self.set_always_on_top = mock.Mock()

        def _fullscreen(self, fullscreen=None):
            self.fullscreen = fullscreen

    def remote(self, players):
        return type('Remote', (), {'players': players})()

    def test_a_press_fullscreens_the_driver_on_the_key(self):
        ver = self.Player('7', 'VER', 'VER')
        nor = self.Player('8', 'NOR', 'NOR', fullscreen=True)
        remote = self.remote([ver, nor])
        self.assertTrue(fb.fullscreen('VER', remote))
        ver.set_fullscreen.assert_called_once_with(fullscreen=True)
        nor.set_fullscreen.assert_called_once_with(fullscreen=False)
        self.assertFalse(fb.fullscreen('VER', remote))
        self.assertEqual(ver.set_fullscreen.call_args_list[-1], mock.call(fullscreen=False))

    def test_qualifying_press_keeps_an_already_fullscreen_onboard_fullscreen(self):
        ver = self.Player('7', 'VER', 'VER', fullscreen=True)
        self.assertTrue(fb.fullscreen('VER', self.remote([ver]), toggle=False))
        ver.set_fullscreen.assert_called_once_with(fullscreen=True)

    def test_the_international_feed_is_never_a_driver_onboard(self):
        remote = self.remote([self.Player('11', 'INTERNATIONAL', None)])
        with self.assertRaises(fb.F1BattleError):
            fb.fullscreen('INTERNATIONAL', remote)

    def test_duplicate_feeds_of_one_driver_resolve_to_the_lowest_id(self):
        first = self.Player('20', 'LAW', 'LAW')
        second = self.Player('23', 'LAW', 'LAW')
        self.assertEqual([p.id for p in fb.onboard_players([second, first], 'LAW')], ['20', '23'])
        fb.fullscreen('LAW', self.remote([second, first]))
        first.set_fullscreen.assert_called_once_with(fullscreen=True)
        second.set_fullscreen.assert_not_called()

    def test_an_absent_driver_fails_instead_of_guessing_a_player(self):
        with self.assertRaises(fb.F1BattleError):
            fb.fullscreen('HAM', self.remote([self.Player('7', 'VER', 'VER')]))


if __name__ == '__main__':
    unittest.main()
