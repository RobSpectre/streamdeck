import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tools import track_status as ts
from tools.track_status import CLEAR, RED, YELLOW


def art(colour=(10, 20, 30, 255), size=ts.SIZE):
    return Image.new('RGBA', (size, size), colour)


class StatusTests(unittest.TestCase):
    def test_the_race_directors_codes_map_to_the_pages_states(self):
        # Yellow flag, safety car, virtual safety car, and the lap it ends on.
        for code in ('2', '4', '6', '7'):
            self.assertEqual(ts.status_of({'Status': code}), YELLOW)
        self.assertEqual(ts.status_of({'Status': '5'}), RED)
        self.assertEqual(ts.status_of({'Status': '1'}), CLEAR)

    def test_a_code_read_as_a_number_is_the_same_reading(self):
        self.assertEqual(ts.status_of({'Status': 4}), YELLOW)
        self.assertEqual(ts.status_of({'Status': ' 6 '}), YELLOW)

    def test_a_code_this_feed_does_not_publish_is_not_a_status(self):
        # Painting the page a status nobody asked for is worse than leaving it.
        for topic in ({'Status': '3'}, {'Status': ''}, {'Status': None}, {}, None, 'yellow'):
            self.assertIsNone(ts.status_of(topic))


class FeedTests(unittest.TestCase):
    def test_a_read_is_reused_within_its_second(self):
        with mock.patch.object(ts, 'fetch', return_value={'Status': '4'}) as fetch:
            feed = ts.StatusFeed()
            self.assertEqual(feed.value(100.0), YELLOW)
            self.assertEqual(feed.value(100.5), YELLOW)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(feed.value(101.5), YELLOW)
            self.assertEqual(fetch.call_count, 2)

    def test_an_unreadable_feed_is_clear_not_the_last_status(self):
        # A session that has ended, or a MultiViewer that has gone away, is not a
        # race still under a red flag.
        with mock.patch.object(ts, 'fetch', side_effect=[{'Status': '5'}, OSError('closed')]):
            feed = ts.StatusFeed()
            self.assertEqual(feed.value(100.0), RED)
            self.assertEqual(feed.value(102.0), CLEAR)

    def test_a_status_this_feed_does_not_publish_leaves_the_page_clear(self):
        with mock.patch.object(ts, 'fetch', return_value={'Status': '9'}):
            self.assertEqual(ts.StatusFeed().value(100.0), CLEAR)


class MarkTests(unittest.TestCase):
    def test_a_clear_track_leaves_the_art_exactly_as_it_is(self):
        self.assertEqual(ts.mark(art(), CLEAR).convert('RGB').getpixel((0, 0)), (10, 20, 30))
        self.assertEqual(ts.mark(art(), CLEAR).convert('RGB').getpixel((72, 72)), (10, 20, 30))

    def test_the_status_is_an_edge_and_the_middle_is_untouched(self):
        for status, colour in ((YELLOW, (255, 212, 71)), (RED, (242, 102, 114))):
            marked = ts.mark(art(), status).convert('RGB')
            self.assertEqual(marked.getpixel((2, 72)), colour)
            self.assertEqual(marked.getpixel((72, ts.MARK-1)), colour)
            self.assertEqual(marked.getpixel((72, ts.MARK)), (10, 20, 30))
            self.assertEqual(marked.getpixel((72, 72)), (10, 20, 30))

    def test_the_art_keeps_its_transparency_outside_the_edge(self):
        # The app composites a key's image itself, so a transparent portrait has
        # to stay transparent everywhere the edge does not cover.
        source = Image.new('RGBA', (ts.SIZE, ts.SIZE), (0, 0, 0, 0))
        marked = ts.mark(source, YELLOW)
        self.assertEqual(marked.getpixel((72, 72))[3], 0)
        self.assertEqual(marked.getpixel((1, 72))[3], 255)

    def test_art_of_another_size_is_fitted_to_the_key(self):
        marked = ts.mark(Image.new('RGBA', (64, 64), (1, 2, 3, 255)), YELLOW)
        self.assertEqual(marked.size, (ts.SIZE, ts.SIZE))


class ArtTests(unittest.TestCase):
    def test_a_png_icon_is_scaled_to_the_key(self):
        found = ts.load_art(ts.ROOT/'images/formula_1/2026/VER.png')
        self.assertEqual(found.size, (ts.SIZE, ts.SIZE))
        self.assertEqual(found.mode, 'RGBA')

    def test_an_svg_view_is_read_as_the_square_at_the_top_of_its_portrait(self):
        # The two hand-made driver views frame the top square of a full-length
        # portrait; that square is what the app shows.
        view = ts.ROOT/'images/formula_1/2026/LAW_redbullracing_2025.svg'
        with Image.open(ts.ROOT/'images/formula_1/2026/LAW_redbullracing_2025.png') as full:
            self.assertEqual(full.size, (1229, 3840))
        self.assertEqual(ts.load_art(view).size, (ts.SIZE, ts.SIZE))

    def test_a_bundle_relative_path_is_read_from_the_built_bundle(self):
        # What a key's settings carry: relative to the bundle, not to whatever
        # directory the plugin happened to be started in.
        bundled = next((ts.ROOT/'opendeck/images/hackparty').glob('*.png'))
        found = ts.load_art('images/hackparty/'+bundled.name)
        self.assertEqual(found.size, (ts.SIZE, ts.SIZE))

    def test_an_svg_with_nothing_embedded_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'flat.svg'
            path.write_text('<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
            with self.assertRaises(ValueError):
                ts.load_art(path)

    def test_a_key_image_is_a_png_data_uri_of_the_key_size(self):
        uri = ts.key_image(str(ts.ROOT/'images/fontawesome/pause.png'), RED)
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        image = Image.open(io.BytesIO(base64.b64decode(uri.split(',', 1)[1])))
        self.assertEqual(image.size, (ts.SIZE, ts.SIZE))
        self.assertEqual(image.convert('RGB').getpixel((72, ts.MARK-1)), (242, 102, 114))
