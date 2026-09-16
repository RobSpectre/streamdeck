import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'mute_mics.sh'

class MuteScriptTests(unittest.TestCase):
    def run_script(self, search_status=0, activate_status=0, active_window="12345"):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            mock=root/'xdotool'
            mock.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
case "$1" in
 search) printf '12345\\n'; exit "$SEARCH_STATUS" ;;
 windowactivate) exit "$ACTIVATE_STATUS" ;;
 getactivewindow) printf '%s\\n' "$ACTIVE_WINDOW" ;;
esac
''')
            mock.chmod(0o755)
            calls=root/'calls'
            result=subprocess.run(['bash',str(SCRIPT)],env=dict(os.environ,PATH=str(root)+':'+os.environ['PATH'],CALLS=str(calls),SEARCH_STATUS=str(search_status),ACTIVATE_STATUS=str(activate_status),ACTIVE_WINDOW=active_window),capture_output=True,text=True)
            return result,calls.read_text().splitlines()

    def test_shortcuts_are_targeted_and_obs_is_not_activated(self):
        result,calls=self.run_script()
        self.assertEqual(result.returncode,0)
        expected=['search --onlyvisible --class ^X-AIR-Edit$','windowactivate 12345','getactivewindow']
        for key in ['Home','shift+m','Right','shift+m']:
            expected += ['getactivewindow',f'key --clearmodifiers --delay 100 {key}']
        self.assertEqual(calls,expected)

    def test_no_keys_when_mixer_is_missing_or_cannot_be_activated(self):
        for search,activate in [(1,0),(0,1)]:
            result,calls=self.run_script(search,activate)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(any(c.startswith('key ') for c in calls))

    def test_focus_mismatch_stops_before_sending_keys(self):
        result,calls=self.run_script(active_window='999')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c.startswith('key ') for c in calls))
