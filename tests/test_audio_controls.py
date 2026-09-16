import tempfile
from pathlib import Path
import subprocess
import unittest
from audio_controls import AudioControls

class AudioTests(unittest.TestCase):
    def test_hot_only_in_broadcast_and_broadcast_resets_mute(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            audio=AudioControls(directory,calls.append)
            self.assertEqual(audio.indicator(),0)
            audio.activate('mic_mute')
            self.assertEqual(audio.indicator(),0)
            audio.activate('audio_mode')
            self.assertEqual(audio.indicator(),1)
            self.assertFalse(audio.state['muted'])
            audio.activate('mic_mute')
            self.assertEqual(audio.indicator(),2)
            self.assertEqual(AudioControls(directory,calls.append).state,audio.state)
            audio.activate('mic_mute')
            self.assertEqual(audio.indicator(),1)
            audio.activate('audio_mode')
            self.assertEqual(audio.indicator(),0)
            audio.activate('audio_mode')
            self.assertEqual(audio.indicator(),1)
            self.assertEqual(calls.count('toggle_audio.sh'),3)
            self.assertEqual(calls.count('mute_mics.sh'),3)

    def test_failed_command_does_not_change_state(self):
        def fail(command):raise subprocess.CalledProcessError(1,command)
        with tempfile.TemporaryDirectory() as directory:
            audio=AudioControls(directory,fail)
            with self.assertRaises(subprocess.CalledProcessError):audio.activate('audio_mode')
            self.assertEqual(audio.state,{'mode':'desktop','muted':False})
            self.assertFalse(audio.path.exists())
