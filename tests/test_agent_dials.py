import base64
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from tools.agent_dials import AgentDials, render, step
from tools.agent_dial_focus import select_screen, codex_title, _CODEX_DOCUMENTS
from tools.claude_dial import parse_picker
from tools.codex_attention import CodexAttention, apply_change
from tools.hermes_model_dials import ModelMonitor, signature, supported_efforts


class AgentDialTests(unittest.TestCase):
    def test_hermes_serving_catalog_precedes_secondary_metadata(self):
        # New routed models can be absent/unsupported in models.dev while the
        # serving provider advertises an explicit, usable effort ladder.
        for provider in ('openrouter', 'nous'):
            reader = Mock(return_value={'supports_reasoning': True,
                                        'supported_efforts': ['max', 'high', 'low', 'none']})
            warm = Mock()
            caps = SimpleNamespace(**{provider+'_model_reasoning_capabilities': reader,
                                     'warm_'+provider+'_reasoning_caps_async': warm})
            metadata = Mock(side_effect=AssertionError('secondary metadata must not gate serving catalog'))
            with patch.dict('sys.modules', {'hermes_cli': SimpleNamespace(models_reasoning_caps=caps),
                                           'agent.models_dev': SimpleNamespace(get_model_capabilities=metadata)}):
                self.assertEqual(supported_efforts(provider, 'moonshotai/Kimi-K3.1-Pro'),
                                 ['max', 'high', 'low', 'none'])
                reader.assert_called_once_with('moonshotai/Kimi-K3.1-Pro')
                warm.assert_called_once_with()
                for detail in (None, {}, {'supports_reasoning': False, 'supported_efforts': ['high']},
                               {'supports_reasoning': True}):
                    reader.return_value = detail
                    self.assertEqual(supported_efforts(provider, 'unknown'), [])
                reader.side_effect = lambda model: ({'supports_reasoning': True, 'supported_efforts': ['high','low']}
                                                   if model == 'moonshotai/kimi-k3.1-pro' else None)
                self.assertEqual(supported_efforts(provider, 'moonshotai/Kimi-K3.1-Pro'), ['high','low'])
                reader.side_effect = lambda model: ({'supports_reasoning': False}
                                                   if model == 'MixedCase' else {'supports_reasoning': True,
                                                                               'supported_efforts': ['high']})
                self.assertEqual(supported_efforts(provider, 'MixedCase'), [])

    def test_missing_accessibility_is_reported_on_the_strip(self):
        d = AgentDials(Mock())
        d.focus = Mock(side_effect=RuntimeError('CodexAccessibilityUnavailable'))
        d.display_state = Mock(return_value={'model': 'Astra', 'reasoning': 'medium', 'detail': 'FOCUS TO CHANGE'})
        settings = {'agent': 'codex', 'parameter': 'reasoning', 'id': 'dial:codex:reasoning'}
        with patch('tools.agent_dials.render', side_effect=lambda a,p,v,detail:detail):
            self.assertEqual(d.snapshot([settings])[settings['id']], 'ENABLE ACCESSIBILITY')
        with self.assertRaises(RuntimeError):
            d.rotate(settings, 1)
        self.assertEqual(d.errors['codex'][1], 'ENABLE ACCESSIBILITY')

    def test_token_updates_do_not_cancel_reasoning_rotation(self):
        attention = Mock()
        d = AgentDials(lambda: attention)
        d.focus = lambda: {'agent': 'codex', 'title': 'Task'}
        old = {'latestModel': 'a', 'latestReasoningEffort': 'medium', 'updatedAt': 1,
               'latestTokenUsageInfo': {'total': {'totalTokens': 100}}}
        fresh = {**old, 'updatedAt': 2, 'latestTokenUsageInfo': {'total': {'totalTokens': 200}}}
        d.codex_state = Mock(side_effect=[('task', old), ('task', fresh)])
        d.catalog = lambda: [{'model': 'a', 'defaultReasoningEffort': 'low',
                             'supportedReasoningEfforts': [{'reasoningEffort': e} for e in ('low', 'medium', 'high')]}]
        d.rotate({'agent': 'codex', 'parameter': 'reasoning'}, 1)
        attention.update_model_settings.assert_called_once_with('task', 'a', 'high', fresh)

    def test_actual_composer_change_still_cancels_rotation(self):
        attention = Mock()
        d = AgentDials(lambda: attention)
        d.focus = lambda: {'agent': 'codex', 'title': 'Task'}
        old = {'latestModel': 'a', 'latestReasoningEffort': 'medium'}
        d.codex_state = Mock(side_effect=[('task', old), ('task', {**old, 'latestReasoningEffort': 'low'})])
        d.catalog = lambda: [{'model': 'a', 'defaultReasoningEffort': 'low',
                             'supportedReasoningEfforts': [{'reasoningEffort': e} for e in ('low', 'medium', 'high')]}]
        with self.assertRaises(RuntimeError):
            d.rotate({'agent': 'codex', 'parameter': 'reasoning'}, 1)
        attention.update_model_settings.assert_not_called()

    def test_codex_composer_effort_wins_over_empty_legacy_and_catalog_default(self):
        attention = Mock()
        state = {'latestModel': 'astra', 'latestReasoningEffort': None,
                 'latestCollaborationMode': {'mode': 'default', 'settings': {'model': 'astra', 'reasoning_effort': 'medium'}}}
        attention.snapshot.return_value = (True, {'task': state})
        d = AgentDials(lambda: attention)
        d.models = [{'model': 'astra', 'defaultReasoningEffort': 'low',
                     'supportedReasoningEfforts': [{'reasoningEffort': e} for e in ('low', 'medium', 'high')]}]
        d.catalog = lambda: d.models
        self.assertEqual(d.display_state('codex', {})['reasoning'], 'medium')
        d.focus = lambda: {'agent': 'codex', 'title': 'Task'}
        d.codex_state = lambda target: ('task', state)
        d.rotate({'agent': 'codex', 'parameter': 'reasoning'}, 1)
        attention.update_model_settings.assert_called_once_with('task', 'astra', 'high', state)
        state['latestCollaborationMode']['settings']['reasoning_effort'] = None
        self.assertEqual(d.display_state('codex', {})['reasoning'], 'DEFAULT')

    def test_compact_composer_settings_do_not_retain_instructions(self):
        state = apply_change({}, {'type': 'snapshot', 'conversationState': {
            'latestCollaborationMode': {'mode': 'default', 'settings': {
                'model': 'astra', 'reasoning_effort': 'medium', 'developer_instructions': 'private'}}}})
        self.assertEqual(state['latestCollaborationMode']['settings'], {'model': 'astra', 'reasoning_effort': 'medium'})
        state = apply_change(state, {'type': 'patches', 'patches': [
            {'op': 'replace', 'path': ['latestCollaborationMode', 'settings', 'developer_instructions'], 'value': 'private'},
            {'op': 'replace', 'path': ['latestCollaborationMode', 'settings', 'reasoning_effort'], 'value': 'high'}]})
        self.assertEqual(state['latestCollaborationMode']['settings'], {'model': 'astra', 'reasoning_effort': 'high'})
        state = apply_change(state, {'type': 'patches', 'patches': [
            {'op': 'replace', 'path': ['latestCollaborationMode', 'settings'],
             'value': {'model': 'astra', 'reasoning_effort': 'low', 'developer_instructions': 'private'}}]})
        self.assertEqual(state['latestCollaborationMode']['settings'], {'model': 'astra', 'reasoning_effort': 'low'})

    def test_unfocused_strip_taps_focus_each_agent_without_confirming(self):
        d = AgentDials(Mock())
        d.focus = lambda: {'agent': None}
        d.claude = Mock()
        with patch('tools.agent_dials.focus_agent') as focus:
            for agent in ('codex', 'claude', 'hermes'):
                for parameter in ('model', 'reasoning'):
                    d.tap({'agent': agent, 'parameter': parameter})
                    focus.assert_called_with(agent)
            self.assertEqual(focus.call_count, 6)
        d.claude.assert_not_called()

    def test_focused_claude_tap_preserves_confirmation_but_busy_tap_sends_nothing(self):
        d = AgentDials(Mock())
        d.focus = lambda: {'agent': 'terminal', 'screen': 'one'}
        d.claude = Mock()
        with patch('tools.agent_dials.focused_cli', return_value={'active': False}), \
                patch('tools.agent_dials.focus_agent') as focus:
            d.tap({'agent': 'claude'})
            d.claude.assert_called_once_with('confirm', d.focus())
            focus.assert_not_called()
        d.claude.reset_mock()
        with patch('tools.agent_dials.focused_cli', return_value={'active': True}):
            d.tap({'agent': 'claude'})
        d.claude.assert_not_called()

    def test_unfocused_agents_keep_live_readings_without_enabling_writes(self):
        attention = Mock()
        attention.snapshot.return_value = (True, {'task': {'latestModel': 'astra', 'latestReasoningEffort': 'high'}})
        d = AgentDials(lambda: attention)
        d.catalog = Mock(return_value=[])
        d.models = [{'model':'astra', 'displayName':'Astra', 'defaultReasoningEffort':'medium'}]
        live = {'claude':[{'pid':1,'session':'c','model':'Opus','effort':'high','updated':1}],
                'hermes':[{'pid':2,'session':'h','model':'DeepSeek','updated':1}]}
        with patch('tools.agent_dials.sessions',side_effect=lambda a: live[a]), \
             patch('tools.agent_dials.read',return_value={}):
            self.assertEqual(d.display_state('codex',{})['model'],'Astra')
            self.assertEqual(d.display_state('codex',{})['reasoning'],'high')
            self.assertEqual(d.display_state('claude',{})['model'],'Opus')
            self.assertEqual(d.display_state('claude',{})['reasoning'],'high')
            self.assertEqual(d.display_state('hermes',{})['model'],'DeepSeek')
            self.assertEqual(d.display_state('hermes',{})['reasoning'],'RESTART HERMES')
        attention.update_model_settings.assert_not_called()
        with self.assertRaises(ValueError): d.codex_state({})

    def test_hermes_dial_drops_the_lab_prefix(self):
        d = AgentDials(lambda: Mock())
        live = [{'pid':2,'session':'h','model':'deepseek-ai/DeepSeek-V4.1-Flash','updated':1}]
        fresh = {'expires': __import__('time').time()+3, 'session':'h', 'model':'Qwen/Qwen3.5-397B-A17B-fast',
                 'reasoning':'medium', 'efforts':['low','medium']}
        with patch('tools.agent_dials.sessions',return_value=live):
            with patch('tools.agent_dials.read',return_value={}):
                self.assertEqual(d.display_state('hermes',{})['model'],'DeepSeek-V4.1-Flash')
            with patch('tools.agent_dials.read',return_value=fresh):
                self.assertEqual(d.display_state('hermes',{})['model'],'Qwen3.5-397B-A17B-fast')

    def test_claude_desktop_session_shows_its_model_but_offers_no_change(self):
        d = AgentDials(lambda: Mock())
        live = [{'pid':1,'session':'c','model':'claude-opus-5-5','effort':'high','updated':1}]
        with patch('tools.agent_dials.sessions',return_value=live), \
                patch('tools.agent_dials.desktop_session',return_value=True):
            state = d.display_state('claude',{})
        self.assertEqual((state['model'],state['reasoning'],state['detail']),('Opus 5.5','high','DESKTOP · VIEW ONLY'))

    def test_last_focused_session_wins_display_only(self):
        d = AgentDials(Mock())
        d.display_sessions['claude'] = 'previous'
        live = [{'pid':1,'session':'previous','model':'Opus','effort':'high','updated':1},
                {'pid':2,'session':'other','model':'Sonnet','effort':'low','updated':2,'active':True}]
        with patch('tools.agent_dials.sessions',return_value=live):
            self.assertEqual(d.display_state('claude',{})['model'],'Opus')

    def test_cached_document_handles_still_read_current_title_and_focus(self):
        api = Mock()
        frame, doc = Mock(), Mock()
        frame.get_state_set.return_value.contains.return_value = True
        doc.get_document_iface.return_value.get_document_attributes.side_effect = [
            {'URI':'app://-/index.html','Title':'First task'},
            {'URI':'app://-/index.html','Title':'Second task'}]
        _CODEX_DOCUMENTS['window'] = [(frame,doc)]
        try:
            self.assertEqual(codex_title('window',api),'First task')
            self.assertEqual(codex_title('window',api),'Second task')
            self.assertEqual(frame.clear_cache.call_count,2)
            self.assertEqual(doc.clear_cache.call_count,2)
            api.get_desktop.assert_not_called()
            frame.get_state_set.return_value.contains.return_value = False
            api.get_desktop.return_value.get_child_count.return_value = 0
            with self.assertRaises(RuntimeError):codex_title('window',api)
        finally:
            _CODEX_DOCUMENTS.clear()

    def test_codex_feedback_waits_for_confirmation(self):
        attention = Mock()
        d = AgentDials(lambda:attention)
        d.focus = lambda: {'agent':'codex','title':'Task'}
        d.codex_state = lambda _: ('task',{'latestModel':'a','latestReasoningEffort':'low'})
        d.catalog = lambda: [{'model':'a','displayName':'A','defaultReasoningEffort':'low',
                             'supportedReasoningEfforts':[{'reasoningEffort':'low'},{'reasoningEffort':'high'}]}]
        attention.update_model_settings.side_effect = RuntimeError('not confirmed')
        with self.assertRaises(RuntimeError):d.rotate({'agent':'codex','parameter':'reasoning'},1)
        attention.update_model_settings.side_effect = None
        with patch('tools.agent_dials.render',side_effect=lambda a,p,v,d:v):
            self.assertEqual(d.rotate({'agent':'codex','parameter':'reasoning'},1),
                             {'dial:codex:model':'A','dial:codex:reasoning':'high'})

    def test_steps_use_native_list_and_stop_at_edges(self):
        self.assertEqual(step(['low','high','max'], 'low', 1), 'high')
        self.assertEqual(step(['low','high'], 'high', 3), 'high')
        with self.assertRaises(ValueError): step(['low','high'], 'medium', 1)
        with self.assertRaises(ValueError): step([], 'low', 1)

    def test_codex_preserves_only_required_state(self):
        state = apply_change({}, {'type':'snapshot','conversationState': {
            'latestReasoningEffort':'high','latestModel':'m','messages':['private']}})
        self.assertEqual(state, {'latestReasoningEffort':'high','latestModel':'m'})

    def test_codex_model_change_uses_supported_default_and_focused_task(self):
        attention = Mock()
        d = AgentDials(lambda: attention)
        d.catalog = lambda: [{'model':'a','supportedReasoningEfforts':[{'reasoningEffort':'high'}], 'defaultReasoningEffort':'high'},
                            {'model':'b','supportedReasoningEfforts':[{'reasoningEffort':'low'}], 'defaultReasoningEffort':'low'}]
        state = {'latestModel':'a','latestReasoningEffort':'high'}
        d.codex_state = lambda _: ('focused-task', state)
        with patch.object(d, 'focus', return_value={'agent':'codex','title':'Unique'}):
            d.rotate({'agent':'codex','parameter':'model'}, 1)
        attention.update_model_settings.assert_called_once_with('focused-task','b','low',state)

    def test_focus_race_never_dispatches(self):
        attention = Mock()
        d = AgentDials(lambda: attention)
        d.catalog = lambda: [{'model':'a','supportedReasoningEfforts':[{'reasoningEffort':'high'}], 'defaultReasoningEffort':'high'}]
        d.codex_state = lambda _: ('task', {'latestModel':'a','latestReasoningEffort':'high'})
        with patch.object(d, 'focus', side_effect=[{'agent':'codex'}, {'agent':None}]):
            with self.assertRaises(RuntimeError): d.rotate({'agent':'codex','parameter':'reasoning'}, 1)
        attention.update_model_settings.assert_not_called()

    def test_duplicate_terminal_titles_require_unique_native_snippet(self):
        metas = [{'id':'a','name':'same','description':'A unique &lt;first&gt; visible terminal snippet'},
                 {'id':'b','name':'same','description':'A different second visible terminal snippet'}]
        self.assertEqual(select_screen('same',metas,'top\nA unique <first> visible terminal snippet\nbottom'),'a')
        with self.assertRaises(RuntimeError): select_screen('same',metas)
        with self.assertRaises(RuntimeError): select_screen('same',metas,'unrelated')
        metas[1]['description'] = metas[0]['description']
        with self.assertRaises(RuntimeError): select_screen('same',metas,'A unique <first> visible terminal snippet')

    def test_claude_picker_uses_native_model_and_effort_only(self):
        text = '''Select model
Switch between Claude models. Your pick becomes the default for new sessions.
  1. Default   Sonnet 5 · Org default
  ❯ 6. Opus (1M context) ✔    Opus 5 with 1M context · Best for everyday
  ● High effort (default) ←/→ to adjust
Enter to set as default · s to use this session only · Esc to cancel'''
        result = parse_picker(text)
        self.assertEqual(result['model'], 'Opus 5 with 1M context')
        self.assertEqual(result['reasoning'], 'HIGH')
        self.assertIsNone(parse_picker(text.replace('s to use this session only','Enter to select')))
        self.assertEqual(parse_picker(text.replace('● High effort (default) ←/→ to adjust','Effort not supported'))['reasoning'],'N/A')

    def test_codex_settings_request_is_conditional_and_task_scoped(self):
        attention = CodexAttention.__new__(CodexAttention)
        attention.sock = object()
        attention.owners = {'task': 'owner'}
        attention.setting_messages = {}
        sent = []
        def send(sock, message):
            sent.append(message)
            event, result = attention.setting_messages[message['requestId']]
            result['applied'] = True
            event.set()
        attention.send = send
        attention.update_model_settings('task','b','low',{'latestModel':'a','latestReasoningEffort':'high'})
        self.assertEqual(sent[0]['version'], 2)
        self.assertEqual(sent[0]['targetClientId'], 'owner')
        self.assertEqual(sent[0]['params'], {'conversationId':'task','activeTurnId':None,
            'threadSettings':{'model':'b','effort':'low'},'condition':{'ifModelEquals':'a','ifEffortEquals':'high'}})

    def test_claude_confirm_never_uses_enter_or_global_model_command(self):
        from tools.claude_dial import run
        target = {'agent':'terminal','screen':'one'}
        with patch('tools.claude_dial.focus',return_value=target), \
             patch('tools.claude_dial.session_for',return_value={'session':'s','active':False}), \
             patch('tools.claude_dial.terminal_text',return_value='native picker'), \
             patch('tools.claude_dial.parse_picker',return_value={'model':'Opus','supported':True}), \
             patch('tools.claude_dial.check_bindings'), \
             patch('tools.claude_dial.subprocess.run') as send:
            run('confirm',target)
            self.assertEqual(send.call_args.args[0],['xdotool','key','--clearmodifiers','s'])

    def test_brand_colors_and_long_models_render(self):
        for agent, color in [('codex',(255,255,255)),('claude',(217,119,87)),('hermes',(0,0,242))]:
            uri = render(agent,'model','deepseek-ai/DeepSeek-V4.1-Flash','FOCUSED SESSION')['background']
            image=Image.open(io.BytesIO(base64.b64decode(uri.split(',')[1])))
            self.assertEqual(image.size,(200,100))
            self.assertEqual(image.getpixel((100,1)),color)

    def test_hermes_stale_command_cannot_reach_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            bridge=SimpleNamespace(CACHE=root,atomic=Mock(),read=lambda p: json.loads(p.read_text()))
            monitor=ModelMonitor(bridge)
            monitor.provider='native';monitor.loaded=__import__('time').monotonic();monitor.models=['one','two']
            cli=SimpleNamespace(model='one',provider='native',reasoning_config={'effort':'low'},
                _agent_running=False,agent=SimpleNamespace(session_id='session'),_app=SimpleNamespace(loop=Mock()),base_url='')
            folder=root/'model-requests';folder.mkdir()
            (folder/'stale.json').write_text(json.dumps({'pid':__import__('os').getpid(), 'expires':0,
                'signature':signature(cli,'session'),'session':'session','parameter':'model','value':'two'}))
            with patch('tools.hermes_model_dials.supported_efforts', return_value=['low','high']): monitor.tick(cli)
            cli._app.loop.call_soon_threadsafe.assert_not_called()
            self.assertFalse((folder/'stale.json').exists())

    def test_hermes_reasoning_request_uses_native_session_only_apply(self):
        import os
        import time
        from tools import cli_agent_bridge as bridge
        with tempfile.TemporaryDirectory() as directory, patch.object(bridge, 'CACHE', Path(directory)):
            callbacks = []
            cli = SimpleNamespace(model='moonshotai/Kimi-K3.1-Pro', provider='openrouter',
                reasoning_config={'effort':'high'}, _agent_running=False,
                agent=SimpleNamespace(session_id='session'), base_url='',
                _app=SimpleNamespace(loop=SimpleNamespace(call_soon_threadsafe=callbacks.append), invalidate=Mock()))
            monitor = ModelMonitor(bridge)
            monitor.provider, monitor.loaded, monitor.models = cli.provider, time.monotonic(), [cli.model]
            focus = {'agent':'hermes', 'pid':os.getpid()}
            request = {'pid':os.getpid(), 'session':'session', 'signature':signature(cli,'session'),
                       'expires':time.time()+5, 'parameter':'reasoning', 'value':'low', 'focus':focus}
            bridge.atomic(bridge.CACHE/'model-requests'/'request.json', request)
            apply = Mock()
            with patch('tools.hermes_model_dials.supported_efforts', return_value=['max','high','low','none']), \
                 patch('tools.hermes_model_dials.subprocess.check_output', return_value=json.dumps(focus)), \
                 patch.dict('sys.modules', {'hermes_cli.cli_model_switch_mixin':
                            SimpleNamespace(_apply_reasoning_after_switch=apply)}):
                monitor.tick(cli)
                self.assertTrue(monitor.pending)
                callbacks.pop()()
            apply.assert_called_once_with(cli, 'low', persist_global=False)
            self.assertFalse(monitor.pending)
            cli._app.invalidate.assert_called_once_with()

if __name__ == '__main__': unittest.main()
