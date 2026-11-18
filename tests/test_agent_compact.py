import json
import os
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from tools import agent_compact
from tools import claude_compact as cc
from tools.cli_agent_bridge import atomic, read
from tools.hermes_model_dials import ModelMonitor


def task(runtime='idle', updated=1, **extra):
    return {'threadRuntimeStatus': {'type': runtime}, 'updatedAt': updated, **extra}


class CodexCompactTests(unittest.TestCase):
    def test_compacts_the_task_its_keys_show(self):
        attention = Mock()
        attention.snapshot.return_value = (True, {'older': task(updated=1), 'shown': task(updated=2)})
        agent_compact.compact('codex', attention)
        attention.compact_thread.assert_called_once_with('shown')

    def test_never_interrupts_a_turn_or_a_waiting_prompt(self):
        waiting = task(requests=[{'method': 'item/tool/requestUserInput'}])
        for states in ({'t': task('active')}, {'t': waiting}, {}):
            attention = Mock()
            attention.snapshot.return_value = (True, states)
            with self.assertRaises(RuntimeError):
                agent_compact.compact('codex', attention)
            attention.compact_thread.assert_not_called()


class HermesCompactTests(unittest.TestCase):
    def run_with_monitor(self, cli, session, live):
        """Drive agent_compact.hermes() against a live ModelMonitor consumer thread."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            monitor = ModelMonitor(SimpleNamespace(CACHE=root, atomic=atomic, read=read))
            stop = threading.Event()
            def consume():
                while not stop.is_set():
                    monitor.compact(cli, session)
                    time.sleep(.01)
            worker = threading.Thread(target=consume)
            worker.start()
            try:
                with patch.object(agent_compact, 'CACHE', root), \
                        patch.object(agent_compact, 'sessions', return_value=live):
                    agent_compact.compact('hermes')
            finally:
                stop.set()
                worker.join(1)
                self.assertEqual(list(root.glob('compact-*/*.json')), [])

    def live(self, **extra):
        return [{'pid': os.getpid(), 'session': 's1', 'updated': 1, 'active': False, **extra}]

    def test_idle_cli_queues_native_compress_as_if_typed(self):
        cli = SimpleNamespace(_agent_running=False, _pending_input=queue.Queue())
        self.run_with_monitor(cli, 's1', self.live())
        self.assertEqual(cli._pending_input.get_nowait(), '/compress')

    def test_busy_or_moved_cli_refuses_and_queues_nothing(self):
        for running, session in ((True, 's1'), (False, 's2')):
            cli = SimpleNamespace(_agent_running=running, _pending_input=queue.Queue())
            with self.assertRaises(RuntimeError):
                self.run_with_monitor(cli, session, self.live())
            self.assertTrue(cli._pending_input.empty())

    def test_open_native_modal_counts_as_busy(self):
        cli = SimpleNamespace(_agent_running=False, _clarify_state=object(), _pending_input=queue.Queue())
        with self.assertRaises(RuntimeError):
            self.run_with_monitor(cli, 's1', self.live())
        self.assertTrue(cli._pending_input.empty())

    def test_active_session_or_silent_plugin_fails_without_waiting_forever(self):
        with patch.object(agent_compact, 'sessions', return_value=self.live(active=True)), \
                self.assertRaises(RuntimeError):
            agent_compact.compact('hermes')
        clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 1, 4]), sleep=Mock(), time=time.time)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(agent_compact, 'CACHE', root), \
                    patch.object(agent_compact, 'sessions', return_value=self.live()), \
                    patch.object(agent_compact, 'time', clock), \
                    self.assertRaisesRegex(RuntimeError, 'restart'):
                agent_compact.compact('hermes')
            self.assertEqual(list(root.glob('compact-*/*.json')), [])

    def test_monitor_ignores_other_clis_and_drops_expired_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            monitor = ModelMonitor(SimpleNamespace(CACHE=root, atomic=atomic, read=read))
            cli = SimpleNamespace(_agent_running=False, _pending_input=queue.Queue())
            other = {'request': 'a'*32, 'pid': os.getpid()+1, 'session': 's1', 'expires': time.time()+3}
            expired = {'request': 'b'*32, 'pid': os.getpid(), 'session': 's1', 'expires': 0}
            atomic(root/'compact-requests'/'other.json', other)
            atomic(root/'compact-requests'/'expired.json', expired)
            monitor.compact(cli, 's1')
            self.assertTrue((root/'compact-requests'/'other.json').exists())
            self.assertFalse((root/'compact-requests'/'expired.json').exists())
            self.assertFalse((root/'compact-results').exists())
            self.assertTrue(cli._pending_input.empty())


class ClaudeCompactTests(unittest.TestCase):
    EMPTY = 'output\n────────────────────\n> \n────────────────────\n  ? for shortcuts'
    TYPED = 'output\n────────────────────\n> /compact\n────────────────────\n  /compact   Clear history'
    DRAFT = 'output\n────────────────────\n> half a thought/compact\n────────────────────'
    MENU = 'Settings\n❯ Auto-compact   true\n  Theme          dark'

    def test_prompt_needs_the_input_box_not_a_quote_or_menu(self):
        self.assertEqual(cc.prompt_line(self.EMPTY), '')
        self.assertEqual(cc.prompt_line(self.TYPED), '/compact')
        self.assertEqual(cc.prompt_line('╭──────────╮\n│ > /compact │\n╰──────────╯'), '/compact')
        self.assertIsNone(cc.prompt_line(self.MENU))
        self.assertIsNone(cc.prompt_line('> a quoted line in an answer'))

    def terminal(self, *screens):
        target = {'window': '1', 'agent': 'terminal', 'screen': 's'}
        with patch.object(cc, 'terminal_target', return_value=['focus']), \
                patch.object(cc, 'focus', return_value=target), \
                patch.object(cc, 'session_for', return_value={'session': 's1'}), \
                patch.object(cc, 'terminal_text', side_effect=screens), \
                patch.object(cc.time, 'sleep'), patch.object(cc.subprocess, 'run') as run:
            try:
                cc.terminal({'pid': 1, 'session': 's1'})
            finally:
                self.sent = [c.args[0] for c in run.call_args_list if c.args[0][0] == 'xdotool']

    def test_types_then_submits_only_an_exact_command(self):
        self.terminal(self.EMPTY, self.TYPED)
        self.assertEqual(self.sent, [['xdotool', 'type', '--clearmodifiers', '--delay', '15', '/compact'],
                                     ['xdotool', 'key', '--clearmodifiers', 'Return']])

    def test_draft_is_restored_and_never_sent(self):
        with self.assertRaises(SystemExit):
            self.terminal(*[self.EMPTY]+[self.DRAFT]*20)
        self.assertEqual(self.sent[-1], ['xdotool', 'key', '--clearmodifiers']+['BackSpace']*8)
        self.assertNotIn('Return', sum(self.sent, []))

    def test_nothing_is_typed_away_from_the_prompt(self):
        with self.assertRaises(SystemExit):
            self.terminal(self.MENU)
        self.assertEqual(self.sent, [])

    def test_busy_desktop_or_vim_sessions_are_refused_before_typing(self):
        live = [{'session': 's1', 'pid': 1, 'active': True}]
        with patch.object(cc, 'sessions', return_value=live), patch.object(cc, 'terminal') as terminal:
            self.assertRaises(SystemExit, cc.main, 's1')
            live[0]['active'] = False
            with patch.object(cc, 'desktop_session', return_value=True):
                self.assertRaises(SystemExit, cc.main, 's1')
            with patch.object(cc.Path, 'read_text', return_value=json.dumps({'editorMode': 'vim'})), \
                    patch.object(cc.Path, 'exists', return_value=True):
                self.assertRaises(SystemExit, cc.main, 's1')
            terminal.assert_not_called()

    def test_deck_side_refuses_busy_and_passes_the_shown_session(self):
        live = [{'session': 'old', 'updated': 1}, {'session': 'shown', 'updated': 2}]
        with patch.object(agent_compact, 'sessions', return_value=live), \
                patch.object(agent_compact.subprocess, 'run') as run:
            agent_compact.compact('claude')
            self.assertEqual(run.call_args.args[0][-1], 'shown')
            live[1]['active'] = True
            live[1]['updated'] = 0
            self.assertRaises(RuntimeError, agent_compact.compact, 'claude')


if __name__ == '__main__':
    unittest.main()
