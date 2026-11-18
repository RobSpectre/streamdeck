#!/usr/bin/env python3
"""Install only this repository's Claude CLI hooks and Hermes CLI plugin."""
from datetime import datetime
import argparse
import shlex
import json
from pathlib import Path
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()


def install_claude():
    from cli_agent_bridge import CACHE, atomic
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    claude = HOME/'.claude/settings.json'
    original = json.loads(claude.read_text())
    shutil.copy2(claude, claude.with_name('settings.opendeck-backup-'+stamp+'.json'))
    old_status = CACHE/'claude-original-statusline.json'
    if not old_status.exists():
        atomic(old_status, original.get('statusLine', {}))
    command = '/usr/bin/python3 '+shlex.quote(str(ROOT/'tools/cli_agent_bridge.py'))
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


def install_hermes():
    from cli_agent_bridge import CACHE, atomic
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
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
    atomic(dest/'runtime.json', {'repo_root': str(ROOT)})
    hermes.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))



def install(agent='both'):
    # Check all requested inputs before changing either agent.
    if agent in ('claude', 'both'):
        json.loads((HOME/'.claude/settings.json').read_text())
    if agent in ('hermes', 'both'):
        yaml.safe_load((HOME/'.hermes/config.yaml').read_text())
    if agent in ('claude', 'both'):
        install_claude()
    if agent in ('hermes', 'both'):
        install_hermes()
    print(f'{agent}: integrations installed with backups. Start new CLI sessions.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', choices=['claude', 'hermes', 'both'], default='both')
    install(parser.parse_args().agent)
