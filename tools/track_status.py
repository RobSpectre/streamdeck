#!/usr/bin/env python3
"""Track status: paint the Formula 1 page for flags, safety cars and stops.

MultiViewer's live timing republishes the race director's track status as a
numeric code (``TrackStatus``). What the deck cares about is three outcomes:
nothing at all, a yellow condition - a yellow flag, a safety car, or a virtual
safety car including the lap where it ends - and a red flag, which stops the
session.

The Formula 1 keys are drawn by the app from their own artwork - and a plugin
cannot touch a key it does not own - so every key on the page is rebuilt as one
of this plugin's own controls, and the builder writes a key-sized copy of each
one's art into the bundle and records its path in that key's settings. This
module draws the status onto that art. No status means no image is sent, so until
the first flag of a session the keys are left exactly as the app drew them.

The status is shown as a coloured edge around each key rather than as a
background. A flag can last many laps and the page has to stay readable while it
is marked, so the art, its glyphs and its colours are left alone and only the
edge of every key on the page carries the colour.

A status that cannot be read is not a flag. A closed MultiViewer, a finished
session or a feed that has gone away returns the page to clear rather than
holding a colour nobody asked for.
"""
import argparse
import base64
import io
import re
import time
from functools import lru_cache
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'http://localhost:10101/api/graphql'
QUERY = '{ liveTimingState { TrackStatus } }'
SIZE = 144
# The width of the coloured edge, in key pixels. Wide enough to read from across
# the desk and around the frames of 37 keys, narrow enough to leave the art alone.
MARK = 10
CLEAR = 'clear'
YELLOW = 'yellow'
RED = 'red'
COLOURS = {YELLOW: '#ffd447', RED: '#f26672'}
# Kinds whose art the plugin draws itself, so there is no app art to mark.
DRAWN = ('f1_battle',)
# The race director's codes. 3 is not a code this feed publishes, and anything
# unrecognised leaves the page alone rather than painting it a status nobody
# asked for.
CODES = {'1': CLEAR,   # all clear
         '2': YELLOW,  # yellow flag
         '4': YELLOW,  # safety car deployed
         '5': RED,     # red flag
         '6': YELLOW,  # virtual safety car deployed
         '7': YELLOW}  # virtual safety car ending


def status_of(topic):
    """The page's status from a track-status topic, or None if it is not one."""
    if not isinstance(topic, dict):
        return None
    return CODES.get(str(topic.get('Status', '')).strip())


def colour(status):
    """The colour a status paints, or None when the track is clear."""
    return COLOURS.get(status)


def fetch(endpoint=ENDPOINT, timeout=5):
    """Read the track-status topic; raises when MultiViewer cannot be reached."""
    response = requests.post(endpoint, json={'query': QUERY}, timeout=timeout)
    response.raise_for_status()
    return ((response.json().get('data') or {}).get('liveTimingState') or {}).get('TrackStatus')


class StatusFeed:
    """One-second cache over the track-status read."""

    def __init__(self, endpoint=ENDPOINT, ttl=1.0):
        self.endpoint, self.ttl = endpoint, ttl
        self.at = None
        self.state = CLEAR

    def value(self, now=None):
        """The status now, re-reading it once the last read has gone stale."""
        now = time.monotonic() if now is None else now
        if self.at is not None and now - self.at < self.ttl:
            return self.state
        self.at = now
        try:
            state = status_of(fetch(self.endpoint))
        except (requests.RequestException, OSError, ValueError, TypeError):
            state = None
        self.state = state or CLEAR
        return self.state


def load_art(path, size=SIZE):
    """One icon as key-sized square RGBA art, at the size the app draws it.

    Two of the Formula 1 driver keys are SVG views, which Pillow cannot read.
    Each of those is a square frame around a full-length portrait, with the
    portrait embedded in it as a data URI and the frame's viewBox selecting the
    square at the top of it; that square is what the app shows, so that is what
    the key's art is built from. Every other icon is already a square PNG.
    """
    path = Path(path)
    if not path.is_absolute():
        # The path in a key's settings is relative to the built bundle, which is
        # installed beside the app's configuration; the copy in this repository is
        # the one the plugin runs from and is installed from the same build.
        path = ROOT/'opendeck'/path
    if path.suffix.lower() == '.svg':
        text = path.read_text(errors='replace')
        embedded = re.search(r'href="data:image/[a-zA-Z0-9.+-]+;base64,([^"]+)"', text)
        if embedded is None:
            raise ValueError(f'{path.name}: no embedded image')
        art = Image.open(io.BytesIO(base64.b64decode(embedded.group(1))))
        box = re.search(r'viewBox="([-\d.eE\s]+)"', text)
        side = min(int(float(box.group(1).split()[2])), art.width) if box else art.width
        art = art.crop((0, 0, side, side))
    else:
        art = Image.open(path)
    art = art.convert('RGBA')
    if art.size != (size, size):
        art = ImageOps.fit(art, (size, size), Image.LANCZOS)
    return art


def mark(art, status, size=SIZE):
    """One key's art with the status shown as a coloured edge, as a flat image.

    The first version of this painted the whole key, which took the page over:
    a flag lasts for many laps and the deck still has to be read during one. The
    status is an edge instead - the art, its glyphs and its colours are all left
    exactly as they are, and a coloured frame round every key is enough to see
    the state of the track at a glance without competing with what is on it.
    """
    image = art if art.mode == 'RGBA' else art.convert('RGBA')
    colour_ = colour(status)
    if colour_ is None:
        return image
    if image.size != (size, size):
        image = ImageOps.fit(image, (size, size), Image.LANCZOS)
    marked = image.copy()
    ImageDraw.Draw(marked).rectangle((0, 0, size-1, size-1), outline=colour_, width=MARK)
    return marked


@lru_cache(maxsize=256)
def key_image(art, status, size=SIZE):
    """The data URI of one key: its art, on the status colour while one is out.

    Cached by art path and status: a status change repaints the whole page, and
    the page asks for the same image again every second it is up.
    """
    return uri(mark(load_art(art, size), status, size))


def uri(image):
    """A PNG data URI, the only image form the app accepts back from a plugin."""
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true',
                        help='report the track status without painting anything')
    parser.add_argument('--art', metavar='PATH', help='one icon to draw a key from')
    parser.add_argument('--status', default=YELLOW, choices=(CLEAR, YELLOW, RED))
    parser.add_argument('--out', default='', help='where to write --art as a PNG')
    arguments = parser.parse_args()
    if arguments.check:
        feed = StatusFeed()
        payload = fetch()
        print(f"status {feed.value()!r} from {payload!r}")
    if arguments.art:
        image = mark(load_art(arguments.art), arguments.status)
        out = Path(arguments.out) if arguments.out else Path(f'/tmp/track-{arguments.status}.png')
        image.save(out)
        print(out)


if __name__ == '__main__':
    main()
