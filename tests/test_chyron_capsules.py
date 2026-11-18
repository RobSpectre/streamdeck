from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from tools import chyron_capsules as capsules


class CapsuleTests(TestCase):
    def setUp(self):
        self.css = 'body { background: transparent; }\n/* custom */\n'
        self.original = self.css
        self.client = Mock()
        self.client.get_input_settings.side_effect = lambda source: SimpleNamespace(
            input_kind='browser_source', input_settings={'css': self.css})
        self.client.set_input_settings.side_effect = self.write
        self.settings = dict(source='Token Chyron - Codex', agent='codex', capsule='model')

    def write(self, source, settings, overlay):
        self.assertEqual(source, self.settings['source'])
        self.assertTrue(overlay)
        self.assertEqual(set(settings), {'css'})
        self.css = settings['css']

    def test_independent_toggles_preserve_custom_css(self):
        other = dict(self.settings, capsule='spark')
        self.assertTrue(capsules.enabled(self.client, self.settings))
        capsules.toggle(self.client, self.settings)
        self.assertFalse(capsules.enabled(self.client, self.settings))
        self.assertTrue(capsules.enabled(self.client, other))
        capsules.toggle(self.client, other)
        capsules.toggle(self.client, self.settings)
        self.assertTrue(capsules.enabled(self.client, self.settings))
        self.assertFalse(capsules.enabled(self.client, other))
        capsules.toggle(self.client, other)
        self.assertEqual(self.css, self.original)

    def test_invalid_or_damaged_rule_does_not_write(self):
        for css in (capsules.rule('codex', 'model').replace('none', 'block'),
                    capsules.rule('codex', 'model') * 2):
            self.css = css
            with self.assertRaises(ValueError):
                capsules.toggle(self.client, self.settings)
        with self.assertRaises(ValueError):
            capsules.toggle(self.client, dict(self.settings, capsule='quota'))
        self.client.set_input_settings.assert_not_called()

    def test_non_browser_source_rejected(self):
        self.client.get_input_settings.side_effect = None
        self.client.get_input_settings.return_value = SimpleNamespace(input_kind='image_source')
        with self.assertRaises(ValueError):
            capsules.toggle(self.client, self.settings)
        self.client.set_input_settings.assert_not_called()

    def test_existing_hidden_preferences_gain_compact_layout_idempotently(self):
        css = capsules.rule('codex', 'model') + '\n' + self.original
        updated = capsules.compact_css(css, 'codex')
        self.assertIn('--od-model', updated)
        self.assertIn('width: calc(100cqw - var(--od-model) - 0.22rem)', updated)
        self.assertTrue(updated.endswith(css))
        self.assertEqual(capsules.compact_css(updated, 'codex'), updated)
        self.css = updated
        capsules.toggle(self.client, self.settings)
        self.assertEqual(self.css, self.original)

    def test_all_hidden_keeps_compact_header(self):
        css = ''.join(capsules.rule('codex', key) + '\n' for key in capsules.CAPSULES)
        updated = capsules.compact_css(css, 'codex')
        self.assertIn('width: max-content', updated)
        self.assertIn('[data-role="capsules"] { display: none', updated)
