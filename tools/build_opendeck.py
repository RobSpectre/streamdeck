#!/usr/bin/env python3
"""Build native OpenDeck profiles from the current layout."""
import argparse
import copy
import hashlib
import json
import re
import shlex
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.label_overrides import read as read_labels, capture as capture_labels, apply as apply_labels, merge as merge_labels

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = 'com.amansprojects.starterpack.sdPlugin'
PREFIX = 'com.amansprojects.starterpack.'
STATUS_PLUGIN = 'party.hack.status.sdPlugin'
STATUS_ACTION = 'party.hack.status.control'
CURRENT = 'opendeck-layout.json'
SOURCES = [ROOT / CURRENT]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def profile_name(source, page, serial=None):
    if serial and source.exists():
        label = json.loads(source.read_text())['devices'].get(serial, {}).get('page_names', {}).get(str(page))
        if label:
            return f'{int(page)+1:02} - {label}'
    return re.sub(r'[^a-zA-Z0-9_-]', '-', source.name) + f'-page-{int(page)+1:02}'


def action(kind):
    names = {'runcommand': ('Run Command', 'runCommand'),
             'switchprofile': ('Switch Profile', 'switchProfile'),
             'multiaction': ('Multi Action', 'multi-action'),
             'toggleaction': ('Toggle Action', 'toggle-action')}
    name, icon = names[kind]
    builtin = kind in ('multiaction', 'toggleaction')
    return dict(name=name, uuid=('opendeck.' if builtin else PREFIX)+kind,
                plugin='opendeck' if builtin else PLUGIN,
                icon=f'opendeck/{icon}.png' if builtin else f'plugins/{PLUGIN}/icons/{icon}.png',
                property_inspector='' if builtin else f'plugins/{PLUGIN}/propertyInspector/{icon}.html',
                states=[{'image': ''}], controllers=['Keypad'],
                supported_in_multi_actions=not builtin, disable_automatic_states=False)


def instance(kind, position, states, settings, children=None, index=0):
    return dict(action=action(kind), context=f'Keypad.{position}.{index}',
                states=copy.deepcopy(states), current_state=0, settings=settings, children=children)


def appearance(s, root, warnings):
    icon = s.get('icon', '')
    if '/streamdeck/' in icon:
        icon = str(root / icon.split('/streamdeck/', 1)[1])
    elif icon and not Path(icon).is_absolute():
        icon = str(root / icon)
    if icon and not Path(icon).is_file():
        warnings.add('Missing icon: '+icon)
    return dict(image=icon, text=s.get('text', ''), show=True,
                colour=s.get('font_color') or '#FFFFFF',
                background_colour=s.get('background_color') or '#000000',
                alignment=s.get('text_vertical_align') or 'bottom',
                family=s.get('font') or 'DejaVu Sans', size=s.get('font_size') or 11)


def convert_state(s, source, device, page, position, root, warnings):
    visual = [appearance(s, root, warnings)]
    for field in ('brightness_change', 'text_horizontal_align'):
        if s.get(field):
            raise ValueError(f'Unsupported nonempty button field {field}: {s[field]}')
    commands = []
    if s.get('command'):
        # Preserve shell syntax, arguments, and backgrounding in the original command.
        commands.append(s['command'])
    if s.get('keys'):
        keys = s['keys'].replace('page_down', 'Page_Down').replace('down', 'Down')
        commands.append('xdotool key --clearmodifiers '+shlex.quote(keys))
    if s.get('write'):
        commands.append('xdotool type --clearmodifiers -- '+shlex.quote(s['write']))
    children = []
    if commands:
        # Separate subshells prevent an original exit/background operator swallowing later input.
        down = 'cd '+shlex.quote(str(root))+' || exit\n'+'export PATH='+shlex.quote(str(root / '.venv/bin'))+':"$PATH"\n'+'\n'.join('( '+c+'\n)' for c in commands)
        children.append(instance('runcommand', position, visual, {'down': down, 'show': False}))
    if s.get('switch_page'):
        target = str(int(s['switch_page'])-1)
        if target not in page:
            raise ValueError(f'Missing destination page {target}')
        children.append(instance('switchprofile', position, visual,
                                 {'device': device, 'profile': profile_name(source, target, device.removeprefix('sd-'))}))
    if len(children) > 1:
        for i, child in enumerate(children, 1):
            child['context'] = f'Keypad.{position}.{i}'
        return instance('multiaction', position, visual, {'delays': [0]*len(children)}, children)
    return children[0] if children else instance('runcommand', position, visual, {})


def build(output, root=ROOT, config_path=None):
    report = {'sources': {}, 'warnings': [], 'upstream_commit': '7cc07942ef4a0d4d04d3011fac3f82626a211cfb'}
    # Remove only profiles listed in our previous generated report.
    previous = output/'migration-report.json'
    if previous.exists():
        old = json.loads(previous.read_text())
        for devices in old['sources'].values():
            for device, info in devices.items():
                for name in info['profiles']:
                    (output/'profiles'/device/(name+'.json')).unlink(missing_ok=True)
                (output/'profiles'/(device+'.json')).unlink(missing_ok=True)
    retired = set(old.get('retired_profiles', [])) if previous.exists() else set()
    if previous.exists():
        retired.update(f'{device}/{name}.json' for devices in old['sources'].values() for device, info in devices.items() for name in info['profiles'])
    warnings = set()
    selectors = {}
    used_images = set()
    for source in sorted(SOURCES, key=lambda p: p.name == CURRENT):
        data = json.loads(source.read_text())
        report['sources'][source.name] = {}
        for serial, config in data['devices'].items():
            device = 'sd-'+serial
            pages = config['buttons']
            report['sources'][source.name][device] = {
                'device_settings': {k:v for k,v in config.items() if k != 'buttons'},
                'profiles': [profile_name(source, p, serial) for p in pages]}
            selectors[device] = {'selected_profile': profile_name(source, config.get('page', 0), serial)}
            for page, buttons in pages.items():
                keys = [None] * (max(map(int, buttons))+1)
                for pos, button in buttons.items():
                    states = button.get('states', {'0': button})
                    ordered = sorted(states, key=int)
                    converted = [convert_state(states[s], source, device, pages, int(pos), root, warnings) for s in ordered]
                    if len(converted) > 1:
                        for i, (sid, child) in enumerate(zip(ordered, converted)):
                            if int(states[sid].get('switch_state', 0)) != int(ordered[(i+1) % len(ordered)])+1 or child['children']:
                                raise ValueError('Only sequential state cycles with single actions are supported')
                            child['context'] = f'Keypad.{pos}.{i+1}'
                        result = instance('toggleaction', int(pos), [c['states'][0] for c in converted], {}, converted)
                        result['current_state'] = ordered.index(str(button.get('state', 0)))
                    else:
                        result = converted[0]
                    if button.get('live_control'):
                        visuals = []
                        for index, icon in enumerate(button['status_icons']):
                            visual = appearance({**states[ordered[0]], 'icon': icon}, root, warnings)
                            visual.update(colour='#ffe7a3' if index == 1 else '#b8c4d4',
                                          background_colour='#201604' if index == 1 else '#10141b')
                            if button.get('status_labels'):
                                visual['text'] = button['status_labels'][index]
                                visual['colour'] = '#ffd9d9' if index == 1 else '#b8c4d4'
                                visual['background_colour'] = '#26090d' if index == 1 else '#10141b'
                            visuals.append(visual)
                        if button['live_control']['kind'] in ('codex_telemetry', 'agent_telemetry'):
                            for visual in visuals:
                                visual.update(text='', show=False)
                        result = instance('runcommand', int(pos), visuals, button['live_control'])
                        result['current_state'] = 0 if button['live_control']['kind'] in ('audio_mode', 'mic_mute', 'codex_response', 'codex_telemetry', 'agent_telemetry', 'agent_action', 'codex_dictation') else 2
                        result['action'] = dict(name='Live broadcast control', uuid=STATUS_ACTION,
                            plugin=STATUS_PLUGIN, states=copy.deepcopy(visuals),
                            icon=f'plugins/{STATUS_PLUGIN}/icon.png', controllers=['Keypad'],
                            disable_automatic_states=True)
                    # Empty slots stay empty; decorative buttons retain their appearance.
                    s = states[ordered[0]]
                    keys[int(pos)] = result if any(s.get(k) for k in ('icon', 'text', 'command', 'keys', 'write', 'switch_page', 'background_color')) or len(states)>1 else None
                for pos, result in enumerate(keys):
                    if result:
                        button = buttons[str(pos)]
                        result['settings']['_label_id'] = button.get('label_id', f'{serial}/{page}/{pos}')
                        result['settings']['_label_defaults'] = [s['text'] for s in result['states']]
                        result['settings']['_label_mode'] = 'shared' if len(set(result['settings']['_label_defaults'])) == 1 else 'per_state'
                profile = {'keys': keys, 'sliders': [], 'infobars': []}
                if config_path:
                    installed = config_path/'profiles'/device/(profile_name(source, page, serial)+'.json')
                    if installed.exists():
                        merge_labels(capture_labels(json.loads(installed.read_text()), profile))
                apply_labels(profile, read_labels()['labels'])
                def bundle_images(item):
                    if item is None:
                        return
                    for state in item['states'] + item['action']['states']:
                        if not state['image']:
                            continue
                        path = Path(state['image'])
                        content = path.read_bytes()
                        relative = Path('images/hackparty')/(hashlib.sha256(content).hexdigest()+path.suffix.lower())
                        used_images.add(relative)
                        destination = output/relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(content)
                        state['image'] = relative.as_posix()
                    for child in item['children'] or []:
                        bundle_images(child)
                for item in keys:
                    bundle_images(item)
                write(output/'profiles'/device/(profile_name(source, page, serial)+'.json'),
                      {'keys': keys, 'sliders': [], 'infobars': []})
    for path in (output/'images/hackparty').glob('*'):
        if path.is_file() and path.relative_to(output) not in used_images:
            path.unlink()
    for device, selector in selectors.items():
        write(output/'profiles'/(device+'.json'), selector)
    active = {f'{device}/{name}.json' for devices in report['sources'].values() for device, info in devices.items() for name in info['profiles']}
    report['retired_profiles'] = sorted(retired - active)
    report['warnings'] = sorted(warnings)
    plugin_dir = output/'plugins'/STATUS_PLUGIN
    write(plugin_dir/'manifest.json', {
        'Name': 'Hackparty Live Status', 'Author': 'hack.party', 'Version': '1.0.0',
        'Description': 'OBS and light controls with live active-state feedback',
        'CodePathLin': 'launch.sh', 'Icon': 'icon',
        'OS': [{'Platform': 'linux'}],
        'Actions': [{'Name': 'Live broadcast control', 'UUID': STATUS_ACTION,
                     'Icon': 'icon', 'Controllers': ['Keypad'], 'DisableAutomaticStates': True,
                     'States': [{'Image': 'icon'}, {'Image': 'icon'}, {'Image': 'icon'}]}]})
    (plugin_dir/'icon.png').write_bytes((ROOT/'images/fontawesome/toggle-on.png').read_bytes())
    launcher = plugin_dir/'launch.sh'
    launcher.write_text(
        '#!/bin/sh\n'
        '# OpenDeck may autostart before the Storage drive is mounted.\n'
        'runtime='+shlex.quote(str(root/'.venv/bin/python'))+'\n'
        'plugin_script='+shlex.quote(str(root/'tools/opendeck_status_plugin.py'))+'\n'
        'while [ ! -x "$runtime" ] || [ ! -r "$plugin_script" ]; do\n'
        '    sleep 2\n'
        'done\n'
        'exec "$runtime" "$plugin_script" "$@"\n')
    launcher.chmod(0o755)
    write(output/'migration-report.json', report)
    write(output/'settings-recommended.json', {'brightness': 86, 'rotation': 0, 'sleep_timeout_minutes': 0})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'opendeck')
    parser.add_argument('--repo-root', type=Path, default=ROOT, help='Runtime location of scripts and icons')
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'opendeck', help='Import app-edited labels from this OpenDeck configuration')
    parser.add_argument('--no-import-labels', action='store_true', help='Skip reading installed profiles (saved overrides still apply)')
    args = parser.parse_args()
    report = build(args.output.resolve(), args.repo_root.resolve(), None if args.no_import_labels else args.config.expanduser().resolve())
    print(f"Built {len(report['sources'])} layout; {len(report['warnings'])} missing icon paths (see migration-report.json).")
