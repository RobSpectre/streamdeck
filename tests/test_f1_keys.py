import unittest
from pathlib import Path
from unittest import mock

from tools import f1_keys as fk


class ScriptTests(unittest.TestCase):
    def test_qualifying_onboard_action_ensures_fullscreen_and_quotes_the_driver(self):
        with mock.patch.object(fk, 'run') as run:
            fk.onboard('nor')
            run.assert_called_once_with('python -m tools.f1_battles --show-onboard NOR')
            for invalid in ('NOR;echo', '', 'NÖR'):
                with self.assertRaises(fk.F1KeyError):
                    fk.onboard(invalid)
    def test_a_command_runs_from_the_repository_with_its_venv(self):
        # What the app's run command action built for these keys, unchanged: the
        # scripts and their state.json are named relative to the repository.
        text = fk.script('mvf1-cli players pause')
        self.assertIn(f'cd {fk.ROOT} || exit', text)
        self.assertIn(str(fk.ROOT/'.venv/bin'), text)
        self.assertIn('( mvf1-cli players pause', text)

    def test_the_repository_path_is_quoted_when_it_needs_to_be(self):
        with mock.patch.object(fk, 'ROOT', Path('/media/scratch/portable space/repo')):
            text = fk.script('true')
        self.assertIn("'/media/scratch/portable space/repo'", text)


class RunTests(unittest.TestCase):
    def test_a_command_is_run_in_the_background(self):
        with mock.patch.object(fk.subprocess, 'Popen') as popen:
            fk.run('mvf1-cli players pause')
        self.assertEqual(popen.call_args.args[0], fk.script('mvf1-cli players pause'))
        self.assertTrue(popen.call_args.kwargs['shell'])
        self.assertTrue(popen.call_args.kwargs['start_new_session'])

    def test_a_key_with_no_command_is_refused(self):
        for command in ('', '   ', None):
            with self.assertRaises(fk.F1KeyError):
                fk.run(command)

    def test_a_command_that_cannot_start_is_reported(self):
        with mock.patch.object(fk.subprocess, 'Popen', side_effect=OSError('no shell')):
            with self.assertRaises(fk.F1KeyError):
                fk.run('mvf1-cli players pause')

    def test_a_driver_press_makes_the_call_the_selector_makes(self):
        with mock.patch.object(fk, 'run') as run:
            fk.driver('VER')
        run.assert_called_once_with(
            'python control_driver_feeds.py driver --driver_abbreviation VER')

    def test_a_driver_press_with_no_driver_is_refused(self):
        for tla in ('', None):
            with self.assertRaises(fk.F1KeyError):
                fk.driver(tla)
