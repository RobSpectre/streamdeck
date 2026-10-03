#!/usr/bin/env python3
"""MultiViewer live-timing battles: detect on-track fights, fullscreen onboards.

The Formula 1 page's rightmost two + XL columns show the closest fights while a
session is being watched. A battle is a pair of cars in consecutive positions
where the trailing car is within the dialled gap (two seconds by default) of the
car ahead and the feed flags it as catching. The leader is the left key of a row,
the trailing car the right; the left key headlines the position being defended,
the right key the gap being closed, and pressing either key fullscreens that
driver's onboard.

The rightmost + XL dial sets that gap in tenths of a second and shows the current
value on its touch strip; the setting is per-workstation, under the private agent
cache, and is not part of the repository.

Timing is read-only from MultiViewer's local GraphQL API. Anything the feed does
not give a position and a numeric interval for is dropped rather than guessed,
so an unavailable reading shows as unavailable instead of a plausible pair.
"""
import argparse
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'http://localhost:10101/api/graphql'
GAP_LIMIT = 2.0
GAP_LIMIT_MIN = 0.5
GAP_LIMIT_MAX = 5.0
GAP_LIMIT_STEP = 0.1
GAP_LIMIT_NAME = 'gap-limit'
# How many laps a battle stands for once it has stopped closing. The feed's
# catching flag and the gap both flicker around the dialled width, and a key that
# blinks out and back is worse than one that lingers after the fight is over.
HOLD_LAPS = 2
BATTLE_LIMIT = 4
SIZE = 144
HEADSHOTS = ROOT/'images/formula_1/2026'
# The headshots are 1000x1000 busts; this window keeps the face centred with
# headroom on every driver in the set.
CROP = (200, -60, 800, 540)
QUERY = '{ liveTimingState { SessionInfo SessionStatus TimingData DriverList TrackStatus } }'
RETRY_SECONDS = 5.0
BACKGROUND = '#10141b'
IDLE = '#344151'
# Gap scale: a second or more is not really a fight, under a second is, and
# under five tenths is the sort of pair that is about to be resolved.
GREEN = '#4bd07a'
YELLOW = '#ffd447'
RED = '#f26672'
PURPLE = '#b56cff'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


class F1BattleError(RuntimeError):
    """A battle key could not act on the timing feed or an onboard player."""


def cache_dir():
    """The private per-workstation cache root the repo's agents share."""
    root = os.environ.get('XDG_CACHE_HOME') or (Path.home()/'.cache')
    return Path(root)/'opendeck-agents'/'f1-battles'


def gap_limit(path=None):
    """The battle width the dial is set to, in seconds.

    An unreadable or out-of-range file falls back to the default rather than
    throwing: the keys must keep working whatever happens to the cache. Reads do
    not create anything, so this is safe to call from tests and diagnostics.
    """
    try:
        value = float(Path(path or (cache_dir()/GAP_LIMIT_NAME)).read_text().strip())
    except (OSError, ValueError):
        return GAP_LIMIT
    return value if math.isfinite(value) and GAP_LIMIT_MIN <= value <= GAP_LIMIT_MAX else GAP_LIMIT


def set_gap_limit(value, path=None):
    """Store the battle width in whole steps of the dial, clamped to its range."""
    if not math.isfinite(value):
        raise ValueError('Nonfinite gap limit')
    steps = max(round(GAP_LIMIT_MIN/GAP_LIMIT_STEP),
                min(round(GAP_LIMIT_MAX/GAP_LIMIT_STEP), round(value/GAP_LIMIT_STEP)))
    value = round(steps*GAP_LIMIT_STEP, 1)
    target = Path(path or (cache_dir()/GAP_LIMIT_NAME))
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    temporary = target.with_name(target.name+'.tmp')
    temporary.write_text(f'{value}\n')
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return value


def gap_text(seconds):
    """The gap as it is shown on a key: hundredths, signed, always positive."""
    return f'+{seconds:.2f}'


def gap_colour(text):
    """Green above a second, yellow below it, red below five tenths.

    The colour follows the number on the key rather than the raw feed value, so
    what is displayed and what is signalled can never disagree.
    """
    try:
        gap = float(str(text).lstrip('+'))
    except ValueError:
        return IDLE
    if gap >= 1:
        return GREEN
    return YELLOW if gap >= 0.5 else RED


def parse_gap(text):
    """Seconds from a feed interval such as '+0.979'; None when it is not one.

    Intervals read like '+0.979', but lapped cars carry '+1 LAP'. Only a finite
    positive number is a gap; everything else is unknown rather than zero.
    """
    if not isinstance(text, str):
        return None
    try:
        value = float(text.strip().lstrip('+'))
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def parse_position(text):
    try:
        return int(str(text))
    except (TypeError, ValueError):
        return None


def on_track(line):
    """A car in the pit lane, stopped or retired is not an on-track battle."""
    return not any(line.get(field) for field in ('InPit', 'PitOut', 'Retired', 'Stopped'))


def drivers_index(driver_list):
    """Racing number -> {tla, colour} from the feed's DriverList topic."""
    index = {}
    for number, driver in (driver_list or {}).items():
        if not isinstance(driver, dict):
            continue
        tla = driver.get('Tla')
        if not isinstance(tla, str) or not tla.strip():
            continue
        colour = driver.get('TeamColour')
        colour = f'#{colour}' if isinstance(colour, str) and len(colour) == 6 else '#b8c4d4'
        index[str(number)] = {'tla': tla.strip().upper(), 'colour': colour,
                              'team': driver.get('TeamName', '')}
    return index


def session_lap(timing):
    """The lap the field is on, used to age a battle.

    Taken from the highest lap count in the timing lines - the leader's - rather
    than from either car in a pair, so an overtake between the two does not reset
    the age. None before anyone has completed a lap, which switches the deck's
    hold off rather than inventing a clock for it.
    """
    laps = [parse_position(line.get('NumberOfLaps'))
            for line in ((timing or {}).get('Lines') or {}).values() if isinstance(line, dict)]
    completed = [lap for lap in laps if lap is not None]
    return max(completed) if completed else None


def pair_key(pair):
    """The pair's two racing numbers, so a fight survives an overtake."""
    return tuple(sorted((pair['ahead']['number'], pair['behind']['number'])))


def battle_pairs(timing, driver_list, gap=GAP_LIMIT):
    """Every on-track pair in consecutive positions with a readable gap.

    Ordered by the leading car's position, so the fight for the lead is the first
    entry and the deck does not reshuffle when a gap changes by a hundredth.
    ``closing`` is the judgement - the trailing car is within ``gap`` and the feed
    flags it as catching - and the rest of the entry is a reading. Positions must
    be consecutive for a pair: the interval a car reports is to the car directly
    ahead of it, and a missing position would otherwise pair two cars a lap apart.
    """
    index = drivers_index(driver_list)
    cars = []
    for number, line in ((timing or {}).get('Lines') or {}).items():
        if not isinstance(line, dict) or not on_track(line):
            continue
        position = parse_position(line.get('Position'))
        driver = index.get(str(number))
        if position is None or driver is None:
            continue
        interval = line.get('IntervalToPositionAhead') or {}
        # The leader has no interval to the car ahead; it is still the car a
        # battle is fought behind, so it stays in the order with an unset gap.
        cars.append(dict(driver, number=str(number), position=position,
                         gap=parse_gap(interval.get('Value')),
                         catching=bool(interval.get('Catching'))))
    cars.sort(key=lambda car: car['position'])
    found = []
    for ahead, behind in zip(cars, cars[1:]):
        if behind['position'] != ahead['position'] + 1 or behind['gap'] is None:
            continue
        found.append({'ahead': ahead, 'behind': behind, 'gap': behind['gap'],
                      'closing': behind['catching'] and behind['gap'] <= gap})
    return found


def battles(timing, driver_list, limit=BATTLE_LIMIT, gap=GAP_LIMIT):
    """The pairs that are closing right now, front of the field first.

    This is the instantaneous reading; the deck's hold, which keeps a battle up
    for a couple of laps after it stops closing, is applied by ``BattleFeed``.
    """
    return [pair for pair in battle_pairs(timing, driver_list, gap) if pair['closing']][:limit]


def fetch(endpoint=ENDPOINT, timeout=1):
    """Read the live-timing topics this module needs; raises when unreachable."""
    response = requests.post(endpoint, json={'query': QUERY}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    state = (payload.get('data') or {}).get('liveTimingState')
    if payload.get('errors') or not isinstance(state, dict):
        raise ValueError('Unavailable MultiViewer timing state')
    if session_mode(state) == 'qualifying':
        # GraphQL's legacy clock omits playback speed. The installed 2.8.4
        # REST clock includes it; read once per shared poll, never per key.
        clock_url = urlparse(endpoint)._replace(path='/api/v2/live-timing/clock', query='', fragment='').geturl()
        try:
            clock = requests.get(clock_url, timeout=timeout)
            clock.raise_for_status()
            state['_clock'] = clock.json()
        except (requests.RequestException, ValueError):
            state['_clock'] = None
    return state


def api_available(endpoint=ENDPOINT):
    """Cheap local availability probe; never starts MultiViewer."""
    address = urlparse(endpoint)
    try:
        with socket.create_connection((address.hostname, address.port or 80), timeout=0.2):
            return True
    except OSError:
        return False


def session_mode(state):
    """Only known competitive session types activate the dynamic keys.

    SessionInfo.Type is Race for both a Grand Prix and Sprint; historical Sprint
    Qualifying races also have Type=Race. Names alone must not override Type.
    """
    info = state.get('SessionInfo') or {}
    session_status = state.get('SessionStatus') or {}
    if not isinstance(info, dict) or not isinstance(session_status, dict):
        return 'hidden'
    status = session_status.get('Status')
    if status not in ('Started', 'Finished'):
        return 'hidden'
    return {'Race': 'race', 'Qualifying': 'qualifying'}.get(info.get('Type'), 'hidden')


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def current_lap_seconds(line, clock, now=None):
    """Elapsed lap time using native playback anchors, in seconds.

    NumberOfLapsTs is generated at a start/finish crossing: replay patches use
    milliseconds relative to liveTimingStartTime, live patches use UTC epoch
    milliseconds. The native REST clock anchors both and supplies replay speed.
    No local stopwatch or previous completed lap is substituted for missing data.
    """
    if not isinstance(clock, dict) or type(clock.get('paused')) is not bool:
        return None
    values = [finite_number(v) for v in (line.get('NumberOfLapsTs'), clock.get('trackTime'),
                                         clock.get('liveTimingStartTime'), clock.get('systemTime'), clock.get('speed'))]
    if any(v is None for v in values):
        return None
    lap_start, track, origin, system, speed = values
    if min(lap_start, track, origin, system, speed) < 0:
        return None
    wall = (time.time() if now is None else now) * 1000
    if not math.isfinite(wall) or wall < system:
        return None
    if not clock['paused']:
        track += (wall - system) * speed
    # Replay lap starts are offsets, live ones are timestamps at/after the
    # native live clock's origin. Compare domains, not a guessed epoch cutoff.
    elapsed = track - lap_start - (origin if lap_start < origin else 0)
    return elapsed / 1000 if elapsed >= 0 else None


def lap_time_text(seconds):
    """Running lap timer in m:ss.s, truncated to the observed tenth."""
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return '—'
    tenths = math.floor(seconds * 10)
    minutes, remainder = divmod(tenths, 600)
    return f'{minutes}:{remainder / 10:04.1f}'


def ordered_items(value):
    """Native sector/segment arrays can also be numeric-keyed JSON objects."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and all(str(k).isdigit() for k in value):
        return [item for _, item in sorted(value.items(), key=lambda entry: int(entry[0]))]
    return []


def lap_colour(line):
    """Colour the timer with the latest current-lap mini-sector judgement.

    Stop at the first not-yet-reported segment, excluding later sectors that
    still carry the preceding lap's colours. No whole-lap prediction is implied.
    Unknown/non-timed segment codes do not become a best-lap claim.
    """
    latest = None
    colours = {2048: YELLOW, 2049: GREEN, 2051: PURPLE}
    for sector in ordered_items(line.get('Sectors')):
        if not isinstance(sector, dict):
            return IDLE
        segments = ordered_items(sector.get('Segments'))
        if not segments:
            return colours.get(latest, IDLE)
        for segment in segments:
            status = segment.get('Status') if isinstance(segment, dict) else None
            if status == 0:
                return colours.get(latest, IDLE)
            if type(status) is not int or status not in colours:
                return IDLE
            latest = status
    return colours.get(latest, IDLE)


def flying_laps(timing, driver_list, clock=None, now=None):
    """Timed-lap candidates from explicit flags, rather than invented pace.

    MultiViewer 2.8.4's status decoder maps bits 2/4/16/32/512 to stopped,
    retired, pit, pit-out and out-lap. A clear status with explicit on-track
    booleans is required. This does not reproduce its private telemetry-based
    hot-lap classifier and cannot reliably exclude unflagged cool-down laps.
    """
    drivers = drivers_index(driver_list)
    cars = []
    for number, line in ((timing or {}).get('Lines') or {}).items():
        if not isinstance(line, dict) or str(number) not in drivers:
            continue
        status = line.get('Status')
        if type(status) is not int or status & (2 | 4 | 16 | 32 | 512):
            continue
        if any(line.get(flag) is not False for flag in ('InPit', 'PitOut', 'Stopped', 'Retired')):
            continue
        if line.get('Outlap') or line.get('KnockedOut'):
            continue
        elapsed = current_lap_seconds(line, clock, now)
        cars.append({**drivers[str(number)], 'number': str(number),
                     'position': parse_position(line.get('Position')),
                     'lap_time': lap_time_text(elapsed),
                     'lap_colour': lap_colour(line) if elapsed is not None else IDLE})
    return qualifying_order(cars)


def qualifying_order(cars: list[dict]) -> list[dict]:
    """Choose up to eight flyers for the + XL's two columns, in reading order."""
    preferred = {'mercedes', 'ferrari', 'red bull racing', 'mclaren'}
    # Team priority comes from DriverList, not hardcoded drivers or car numbers.
    # Within each group, timing position keeps the front of the field at the top.
    return sorted(cars, key=lambda car: (str(car.get('team', '')).strip().casefold() not in preferred,
                                        car['position'] if car['position'] is not None else math.inf,
                                        car['number']))[:BATTLE_LIMIT * 2]


class BattleFeed:
    """One-second cache over the live-timing read shared by all battle keys."""

    def __init__(self, endpoint=ENDPOINT, ttl=1.0):
        self.endpoint, self.ttl = endpoint, ttl
        self.lock = threading.Lock()
        self.at = None
        self.rows = []
        self.available = False
        self.mode = 'hidden'
        self.track_status = None
        self.session = None
        # Pair key -> the last lap it was closing on, which is what the hold is
        # measured from.
        self.seen = {}

    def pause(self):
        """Drop page-local state; no timing reads occur while the page is hidden."""
        with self.lock:
            self.at = None
            self.rows, self.seen = [], {}
            self.available, self.mode = False, 'hidden'
            self.track_status, self.session = None, None

    def slot(self, slot):
        if not self.available or self.mode == 'hidden':
            return ('hidden', '', '', '', IDLE, '')
        if self.mode == 'qualifying':
            index = int(slot)
            if not 0 <= index < len(self.rows):
                return ('no_flyer', '', '', '', IDLE, '')
            car = self.rows[index]
            return ('flying', car['tla'], car.get('lap_time', '—'), car.get('lap_colour', IDLE),
                    car['colour'], car['position'])
        return slot_value(self.rows, self.available, slot)

    def shown(self, pairs, lap):
        """The pairs to show: the closing ones and the ones still standing.

        The catching flag and the gap both flicker around the threshold, so
        showing only the instantaneous reading blanks and reshuffles the keys
        every second. A pair that has closed at some point in the last
        ``HOLD_LAPS`` laps keeps its place - drawn with its live gap - whether or
        not it is closing right now, and two laps of not closing is long enough
        to call the fight off.

        Only the closing judgement is held. A car that pits, stops or retires is
        not in the candidate list at all, so it leaves at once, and so does a pair
        that stops being consecutive in position. A lap that has gone backwards
        means a new session, and nothing is carried over.
        """
        if lap is None:
            self.seen = {}
            return [pair for pair in pairs if pair['closing']][:BATTLE_LIMIT]
        current = {pair_key(pair) for pair in pairs}
        self.seen = {key: seen for key, seen in self.seen.items() if key in current}
        self.seen.update({pair_key(pair): lap for pair in pairs if pair['closing']})

        def standing(pair):
            last = self.seen.get(pair_key(pair))
            return last is not None and 0 <= lap - last < HOLD_LAPS

        return [pair for pair in pairs if pair['closing'] or standing(pair)][:BATTLE_LIMIT]

    def value(self, now=None, refresh=True):
        """(battles, available). A press reads the cache rather than re-reading.

        The keys show what the last poll saw; refreshing on the press could
        fullscreen a different driver than the one on the key.
        """
        with self.lock:
            now = time.monotonic() if now is None else now
            interval = self.ttl if self.available else RETRY_SECONDS
            if refresh and (self.at is None or now - self.at >= interval):
                self.at = now
                try:
                    if not api_available(self.endpoint):
                        raise OSError('MultiViewer API is offline')
                    state = fetch(self.endpoint)
                    from tools.track_status import status_of
                    track = state.get('TrackStatus')
                    self.track_status = status_of(track) if isinstance(track, dict) else None
                    mode = session_mode(state)
                    info = state.get('SessionInfo') or {}
                    if not isinstance(info, dict):
                        raise ValueError('Invalid session information')
                    session = (info.get('Key'), info.get('Path'), mode)
                    if session != self.session:
                        self.seen = {}
                    self.session, self.mode = session, mode
                    timing = state.get('TimingData')
                    drivers = state.get('DriverList')
                    if any(topic is not None and not isinstance(topic, dict) for topic in (timing, drivers)):
                        raise ValueError('Invalid timing topics')
                    if timing and not isinstance(timing.get('Lines', {}), dict):
                        raise ValueError('Invalid timing lines')
                    if mode == 'race':
                        pairs = battle_pairs(timing, drivers, gap=gap_limit())
                        self.rows = self.shown(pairs, session_lap(timing))
                    elif mode == 'qualifying':
                        self.rows = flying_laps(timing, drivers, state.get('_clock'))
                    else:
                        self.rows, self.seen = [], {}
                    self.available = True
                except (requests.RequestException, OSError, ValueError, TypeError):
                    # Keep `seen`: a moment of unreadable feed must not restart
                    # every hold, and an old lap count cannot make a stale pair
                    # stand once the clock has moved on.
                    self.rows, self.available = [], False
                    self.mode, self.track_status = 'hidden', None
            return self.rows, self.available


def slot_value(rows, available, slot):
    """The render value for one key: leader on even slots, trailer on odd."""
    if not available:
        return ('unavailable', '', '', '', IDLE, '')
    index, side = divmod(int(slot), 2)
    if index >= len(rows):
        return ('empty', '', '', '', IDLE, '')
    battle = rows[index]
    car = battle['ahead'] if side == 0 else battle['behind']
    return ('battle', car['tla'], gap_text(battle['gap']), 'lead' if side == 0 else 'trail',
            car['colour'], car['position'])


@lru_cache(maxsize=32)
def headshot(tla):
    """A prepared 144x144 crop of the driver's 2026 headshot, or None."""
    from PIL import Image
    path = HEADSHOTS/f'{tla}.png'
    if not path.is_file():
        return None
    return Image.open(path).convert('RGBA').crop(CROP).resize((SIZE, SIZE), Image.LANCZOS)


def fit_bold(draw, text, limit=SIZE-24, maximum=62, minimum=17):
    """The largest bold size that fits one line inside ``limit`` pixels."""
    from PIL import ImageFont
    size = maximum
    while size > minimum and draw.textlength(text, font=ImageFont.truetype(BOLD, size)) > limit:
        size -= 1
    return ImageFont.truetype(BOLD, size)


def headline(value):
    """(big text, its colour) for one battle key.

    The leading driver's key headlines the position it is defending, the trailing
    driver's the gap it is closing. One number per key: the acronym above names
    the driver, and the size says which half of the fight this key is. The white
    position is the order, the coloured gap is what is happening.
    """
    state, tla, gap, side, colour, position = value
    if state == 'flying':
        return gap or '—', side if side in (YELLOW, GREEN, PURPLE) else IDLE
    if side == 'lead':
        return (f'P{position}' if isinstance(position, int) else '—'), '#ffffff'
    return gap, gap_colour(gap)


@lru_cache(maxsize=128)
def render(value, status=None):
    """144x144 PNG data URI for one battle key.

    One number fills the key: the leading driver's key shows the position being
    defended, the trailing driver's key the gap being closed, in the colour that
    says how close the fight is. The acronym above names the driver, and the
    outline stays the team colour - the big number is what is happening.

    A flag is added as a coloured edge round the card, so the fight is still the
    thing being read.
    """
    from PIL import Image, ImageDraw, ImageFont
    from tools.track_status import mark
    state, tla, gap, side, colour, position = value
    image = Image.new('RGBA', (SIZE, SIZE), '#000000' if state == 'hidden' else BACKGROUND)
    if state == 'hidden':
        return 'data:image/png;base64,' + _encode(image.convert('RGB'))
    if state in ('battle', 'flying'):
        # A driver with no headshot asset keeps the plain dark card; the acronym
        # and the big number still say who the key is for and what it is doing.
        photo = headshot(tla)
        if photo is not None:
            image.paste(photo, (0, 0), photo)
            image = Image.alpha_composite(image, Image.new('RGBA', (SIZE, SIZE), (16, 20, 27, 185)))
    image = image.convert('RGB')
    draw = ImageDraw.Draw(image)
    if state in ('battle', 'flying'):
        big, big_colour = headline(value)
        # The outline of the glyphs keeps them legible over a suit or a helmet.
        draw.text((SIZE/2, 21), tla, font=ImageFont.truetype(BOLD, 21), fill='#ffffff',
                  anchor='mm', stroke_width=3, stroke_fill='#0b0e13')
        draw.text((SIZE/2, 88), big, font=fit_bold(draw, big), fill=big_colour,
                  anchor='mm', stroke_width=4, stroke_fill='#0b0e13')
    else:
        label = {'unavailable': 'NO TIMING', 'no_flyer': 'NO FLYING LAP'}.get(state, 'NO BATTLE')
        draw.text((SIZE/2, SIZE/2), label, font=ImageFont.truetype(BOLD, 15),
                  fill='#8797aa', anchor='mm')
    draw.rounded_rectangle((4, 4, SIZE-5, SIZE-5), radius=13,
                           outline=colour, width=2 if state in ('battle', 'flying') else 1)
    return 'data:image/png;base64,' + _encode(mark(image, status))


def _encode(image):
    import base64
    import io
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return base64.b64encode(stream.getvalue()).decode()


def onboard_players(players, tla):
    """Onboard feeds for one driver, lowest player id first.

    More than one player can hold the same driver (an old and a new feed), so
    the choice is deterministic rather than the most recent one.
    """
    return sorted((player for player in players
                   if player.title == tla and (player.driver_data or {}).get('tla') == tla),
                  key=lambda player: int(player.id))


def fullscreen(tla, remote=None, toggle=True):
    """Fullscreen the driver's onboard, or restore it when already fullscreen.

    Returns True when the driver went fullscreen and False when it was restored.
    Only onboard feeds of the whole grid are considered; the international feed
    has no driver. Nothing is written to the driver-feed state file, so the
    target/rotate helpers on the XL are unaffected.
    """
    if remote is None:
        from mvf1 import MultiViewerForF1
        remote = MultiViewerForF1()
    players = remote.players
    candidates = onboard_players(players, tla)
    if not candidates:
        raise F1BattleError(f'No onboard player for {tla}')
    target = candidates[0]
    if target.fullscreen and toggle:
        target.set_fullscreen(fullscreen=False)
        return False
    for player in players:
        if player.fullscreen and player is not target:
            player.set_fullscreen(fullscreen=False)
    target.set_fullscreen(fullscreen=True)
    target.set_always_on_top(always_on_top=False)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fullscreen', metavar='TLA',
                        help='Fullscreen or restore one driver onboard, then exit')
    parser.add_argument('--show-onboard', metavar='TLA',
                        help='Ensure a driver onboard is fullscreen, then exit')
    args = parser.parse_args()
    if args.show_onboard:
        fullscreen(args.show_onboard.upper(), toggle=False)
        print('fullscreen')
        return
    if args.fullscreen:
        print('fullscreen' if fullscreen(args.fullscreen.upper()) else 'restored')
        return
    feed = BattleFeed(ttl=0)
    rows, available = feed.value(refresh=True)
    if not available:
        print('MultiViewer live timing is unavailable.')
        return
    if feed.mode == 'hidden':
        print('No supported competitive session.')
        return
    if not rows:
        print('No timed-lap candidates.' if feed.mode == 'qualifying' else 'No active battles.')
        return
    if feed.mode == 'qualifying':
        for car in rows:
            print(f"{car['tla']} · timed lap (P{car['position']})")
        return
    for battle in rows:
        print(f"{battle['ahead']['tla']} (P{battle['ahead']['position']}) "
              f"leads {battle['behind']['tla']} (P{battle['behind']['position']}) "
              f"by {gap_text(battle['gap'])}")
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
