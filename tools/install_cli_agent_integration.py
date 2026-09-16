#!/usr/bin/env python3
"""Install only this repository's Claude CLI hooks and Hermes CLI plugin."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()


def install():
    from cli_agent_bridge import CACHE, atomic
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    claude = HOME/'.claude/settings.json'
    original = json.loads(claude.read_text())
    shutil.copy2(claude, claude.with_name('settings.opendeck-backup-'+stamp+'.json'))
    old_status = CACHE/'claude-original-statusline.json'
    if not old_status.exists():
        atomic(old_status, original.get('statusLine', {}))
    command = f'/usr/bin/python3 {ROOT}/tools/cli_agent_bridge.py'
    original['statusLine'] = {**original.get('statusLine', {}), 'type': 'command',
                              'command': command+' status', 'refreshInterval': 5}
    hooks = original.setdefault('hooks', {})
    for event in ['SessionStart', 'UserPromptSubmit', 'Stop', 'StopFailure', 'SessionEnd', 'PermissionRequest', 'Notification']:
        entries = hooks.setdefault(event, [])
        if not any(h.get('command') == command+' hook' for e in entries for h in e.get('hooks', [])):
            group = {'hooks': [{'type': 'command', 'command': command+' hook', 'timeout': 310 if event == 'PermissionRequest' else 5}]}
            if event == 'Notification':
                group['matcher'] = 'idle_prompt'
            entries.append(group)
    atomic(claude, original)
    hermes = HOME/'.hermes/config.yaml'
    shutil.copy2(hermes, hermes.with_name('config.opendeck-backup-'+stamp+'.yaml'))
    config = yaml.safe_load(hermes.read_text()) or {}
    plugins = config.setdefault('plugins', {})
    enabled = plugins.setdefault('enabled', [])
    if 'opendeck-cli' not in enabled:
        enabled.append('opendeck-cli')
    if 'opendeck-cli' in plugins.get('disabled', []):
        plugins['disabled'].remove('opendeck-cli')
    approval = config.setdefault('security', {}).setdefault('approval', {})
    approval['transport'] = 'opendeck-cli'
    approval['transport_fallback'] = 'builtin'
    dest = HOME/'.hermes/plugins/opendeck-cli'
    if dest.exists():
        shutil.copytree(dest, CACHE/('hermes-plugin-backup-'+stamp))
    shutil.copytree(ROOT/'integrations/hermes-opendeck', dest, dirs_exist_ok=True)
    hermes.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    print('Claude CLI hooks and Hermes CLI plugin installed; original settings backed up.')


if __name__ == '__main__':
    install()
