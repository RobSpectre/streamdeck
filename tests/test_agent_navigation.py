import unittest
from unittest.mock import patch
from tools import agent_navigation as nav

class NavigationTests(unittest.TestCase):
    def test_focus_keys_target_their_agent(self):
        with patch.object(nav, 'focus_agent') as focus:
            for agent in ('codex','claude','hermes'):
                for metric in ('activity','context','session'):
                    nav.activate(agent, metric)
                    focus.assert_called_with(agent)

    def test_web_keys_use_usage_and_billing_and_quota_is_unchanged(self):
        with patch.object(nav.subprocess, 'Popen') as launch:
            nav.activate('hermes','speed')
            self.assertEqual(launch.call_args.args[0],['xdg-open','https://tokenfactory.nebius.com/organization/usage'])
            nav.activate('hermes','month')
            self.assertEqual(launch.call_args.args[0],['xdg-open','https://tokenfactory.nebius.com/organization/payments'])
            launch.reset_mock();nav.activate('codex','quota');launch.assert_not_called()

    def test_terminal_focus_uses_exact_screen_id_not_window_title(self):
        env=b'GNOME_TERMINAL_SCREEN=/org/gnome/Terminal/screen/be09f2f2_abd9_46cf_8128_a2fd7a5f7582\0GNOME_TERMINAL_SERVICE=:1.134\0'
        with patch.object(nav.Path, 'read_bytes', return_value=env), patch.object(nav.time, 'monotonic', return_value=1):
            command=nav.terminal_target(123)
        self.assertEqual(command[-3:],['be09f2f2-abd9-46cf-8128-a2fd7a5f7582','[]','1000'])
        self.assertIn(':1.134',command)

    def test_codex_does_not_focus_an_unrelated_chatgpt_window(self):
        with patch.object(nav,'windows',return_value=[('1','WM_CLASS = "other", "Chatgpt"'),('2','WM_CLASS = "chatgpt (/home/user/.config/Codex)", "Chatgpt"')]),patch.object(nav.subprocess,'run') as run:
            nav.focus_agent('codex')
        self.assertEqual(run.call_args.args[0],['xdotool','windowactivate','--sync','2'])
