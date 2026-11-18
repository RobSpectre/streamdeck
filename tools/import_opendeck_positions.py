#!/usr/bin/env python3
"""Adopt saved OpenDeck key positions without importing rendered runtime state."""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def adopt(layout, profiles):
    """Profiles are keyed by (serial, page). Unknown/ambiguous identities fail closed."""
    result = copy.deepcopy(layout)
    for serial, device in layout['devices'].items():
        known = {}
        for page, buttons in device['buttons'].items():
            for position, button in buttons.items():
                identity = button.get('label_id', f'{serial}/{page}/{position}')
                candidate = copy.deepcopy(button)
                candidate['label_id'] = identity
                if identity in known and known[identity] != candidate:
                    raise ValueError(f'Ambiguous source identity: {identity}')
                known[identity] = candidate
        for page, buttons in device['buttons'].items():
            profile = profiles[(serial, page)]
            if len(profile['keys']) != max(map(int, buttons)) + 1:
                raise ValueError(f'Unexpected key count: {serial}/{page}')
            moved = {}
            for position, key in enumerate(profile['keys']):
                if key is None:
                    moved[str(position)] = {'states': {'0': {}}}
                    continue
                identity = key.get('settings', {}).get('_label_id')
                if identity not in known:
                    raise ValueError(f'Unknown key at {serial}/{page}/{position}: {identity}')
                moved[str(position)] = copy.deepcopy(known[identity])
            expected = []
            for position in range(len(profile['keys'])):
                button = buttons[str(position)]
                states = button.get('states', {'0': button})
                first = states[min(states, key=int)]
                occupied = len(states) > 1 or any(first.get(k) for k in
                    ('icon', 'text', 'command', 'keys', 'write', 'switch_page', 'background_color'))
                expected.append(button.get('label_id', f'{serial}/{page}/{position}') if occupied else None)
            if expected != positions(profile):
                result['devices'][serial]['buttons'][page] = moved
    return result


def read_profiles(layout, config):
    profiles, raw = {}, {}
    for serial, device in layout['devices'].items():
        for page in device['buttons']:
            name = f"{int(page)+1:02} - {device['page_names'][page]}.json"
            path = config/'profiles'/('sd-'+serial)/name
            content = path.read_bytes()
            raw[path] = content
            profiles[(serial, page)] = json.loads(content)
    return profiles, raw


def positions(profile):
    return [key.get('settings', {}).get('_label_id') if key else None for key in profile['keys']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home()/'.config/opendeck')
    parser.add_argument('--write', action='store_true', help='Save layout after validation (default: preview only)')
    args = parser.parse_args()
    source = ROOT/'opendeck-layout.json'
    layout = json.loads(source.read_text())
    profiles, raw = read_profiles(layout, args.config)
    updated = adopt(layout, profiles)
    changes = []
    for serial, device in layout['devices'].items():
        for page, buttons in device['buttons'].items():
            generated = ROOT/'opendeck/profiles'/('sd-'+serial)/f"{int(page)+1:02} - {device['page_names'][page]}.json"
            if positions(json.loads(generated.read_text())) != positions(profiles[(serial, page)]):
                changes.append(f"{serial}: {device['page_names'][page]}")
    print('\n'.join(changes) or 'Positions already match generated profiles.')
    if not args.write:
        return
    # Refuse a moving snapshot; do not overwrite live OpenDeck profiles at all.
    for path, content in raw.items():
        if positions(json.loads(path.read_bytes())) != positions(json.loads(content)):
            raise RuntimeError('OpenDeck positions changed during capture; retry')
    backup = Path(tempfile.mkdtemp(prefix='opendeck-positions-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'))
    shutil.copy2(source, backup/source.name)
    shutil.copy2(ROOT/'opendeck-labels.json', backup/'opendeck-labels.json')
    for path, content in raw.items():
        target = backup/path.relative_to(args.config)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    temporary = source.with_suffix('.tmp')
    temporary.write_text(json.dumps(updated, indent=2, ensure_ascii=False)+'\n')
    temporary.replace(source)
    print(f'Adopted positions across {len(profiles)} profiles. Backup: {backup}')


if __name__ == '__main__':
    main()
