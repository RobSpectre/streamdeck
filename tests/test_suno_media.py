import unittest
from tools.suno_media import suno_url, transport_name, unique, click
from unittest.mock import Mock


class SunoMediaTests(unittest.TestCase):
    def test_only_suno_https_origin_is_accepted(self):
        for url in ('https://suno.com/discover', 'https://www.suno.com/song/example'):
            self.assertTrue(suno_url(url))
        for url in ('https://suno.com.evil.test/', 'https://evil.test/?suno.com',
                    'https://suno.com@evil.test/', 'http://suno.com/', 'about:blank'):
            self.assertFalse(suno_url(url))

    def test_only_playbar_actions_not_carousels_or_song_cards(self):
        self.assertTrue(transport_name('Playbar: Play button', 'play'))
        self.assertTrue(transport_name('Playbar: Pause button', 'play'))
        self.assertTrue(transport_name('Playbar: Next Song button', 'next'))
        for name in ('Next', 'Play For You', 'Play song', 'Playbar: Previous Song button'):
            self.assertFalse(transport_name(name, 'next'))
            self.assertFalse(transport_name(name, 'play'))

    def test_no_guessing_when_target_is_missing_or_ambiguous(self):
        for candidates in ([], [1, 2]):
            with self.assertRaises(RuntimeError):
                unique(candidates, 'target')
        self.assertEqual(unique([1], 'target'), 1)

    def test_default_action_not_context_menu(self):
        node = Mock()
        action = node.get_action_iface.return_value
        action.get_n_actions.return_value = 2
        action.get_action_name.side_effect = ['showContextMenu', 'doDefault']
        action.do_action.return_value = True
        click(node)
        action.do_action.assert_called_once_with(1)

class SpotifyPriorityTests(unittest.TestCase):
    def test_open_spotify_wins_over_suno(self):
        from unittest.mock import patch
        from tools import suno_media as media
        with patch.object(media, 'spotify_control', return_value=True) as spotify, patch.object(media, 'suno_control') as suno:
            media.run('next')
            spotify.assert_called_once_with('next', False)
            suno.assert_not_called()

    def test_absent_spotify_falls_back_but_failure_does_not(self):
        from unittest.mock import patch
        from tools import suno_media as media
        with patch.object(media, 'spotify_control', return_value=False) as spotify, patch.object(media, 'suno_control') as suno:
            media.run('play', True)
            suno.assert_called_once_with('play', True)
            suno.reset_mock()
            spotify.side_effect = RuntimeError('Spotify unavailable')
            with self.assertRaises(RuntimeError):
                media.run('play')
            suno.assert_not_called()

    def test_spotify_dispatch_binds_owner_and_uses_correct_method(self):
        from unittest.mock import patch
        from tools import suno_media as media
        for action, method in [('play', 'PlayPause'), ('next', 'Next')]:
            replies = [(['org.mpris.MediaPlayer2.chromium', 'org.mpris.MediaPlayer2.spotify'],),
                       (':1.999',), ({'CanControl': True, 'CanPause': True, 'CanGoNext': True, 'PlaybackStatus': 'Playing'},), ()]
            with patch.object(media, 'dbus_call', side_effect=replies) as call:
                self.assertTrue(media.spotify_control(action))
                self.assertEqual(call.call_args.args, (':1.999', '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player', method))

    def test_check_does_not_send_playback_and_other_players_are_ignored(self):
        from unittest.mock import patch
        from tools import suno_media as media
        with patch.object(media, 'dbus_call', return_value=(['org.mpris.MediaPlayer2.chromium', 'org.mpris.MediaPlayer2.spotifyFake'],)):
            self.assertFalse(media.spotify_control('play'))
        replies = [(['org.mpris.MediaPlayer2.spotify'],), (':1.999',),
                   ({'CanControl': True, 'CanPlay': True, 'PlaybackStatus': 'Paused'},)]
        with patch.object(media, 'dbus_call', side_effect=replies) as call, patch('builtins.print'):
            self.assertTrue(media.spotify_control('play', check=True))
            self.assertEqual(call.call_count, 3)
