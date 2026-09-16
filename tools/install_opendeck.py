#!/usr/bin/env python3
"""Install the generated current Hackparty layout with a backup of existing profiles."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def install(config):
    if subprocess.run(['pgrep', '-x', 'opendeck'], capture_output=True).returncode == 0:
        raise SystemExit('Quit OpenDeck completely before installing to prevent it overwriting these files.')
    bundle = ROOT/'opendeck'
    report = json.loads((bundle/'migration-report.json').read_text())
    if set(report['sources']) != {'opendeck-layout.json'}:
        raise SystemExit('Regenerate the bundle from the current configuration first.')
    if not (config/'plugins/com.amansprojects.starterpack.sdPlugin').is_dir():
        raise SystemExit('Install OpenDeck Starter Pack before installing profiles.')
    backup = config.parent/(config.name+'.profiles-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    profiles = config/'profiles'
    if profiles.exists():
        shutil.copytree(profiles, backup)
    profiles.mkdir(parents=True, exist_ok=True)
    from label_overrides import capture, merge, apply, read
    # Capture before overwriting anything, including edits made since generation.
    staged = {}
    for generated in (bundle/'profiles').glob('*/*.json'):
        relative = generated.relative_to(bundle/'profiles')
        fresh = json.loads(generated.read_text())
        installed = profiles/relative
        if installed.exists():
            merge(capture(json.loads(installed.read_text()), fresh))
        staged[relative] = fresh
    overrides = read()['labels']
    for fresh in staged.values():
        apply(fresh, overrides)
    # Historical filenames are recorded in the bundle; old snapshots are unnecessary.
    for relative in report.get('retired_profiles', []):
        target = profiles/relative
        if not target.resolve().is_relative_to(profiles.resolve()):
            raise ValueError('Invalid retired profile path')
        target.unlink(missing_ok=True)
    # Remove an obsolete selector only if it still points to our historical layout.
    old = profiles/'sd-AL14J2C08719.json'
    if old.exists() and json.loads(old.read_text()).get('selected_profile', '').startswith('streamdeck_ui_'):
        old.unlink()
    shutil.copytree(bundle/'plugins', config/'plugins', dirs_exist_ok=True)
    shutil.copytree(bundle/'images', config/'images', dirs_exist_ok=True)
    shutil.copytree(bundle/'profiles', profiles, dirs_exist_ok=True)
    for relative, fresh in staged.items():
        (profiles/relative).write_text(json.dumps(fresh, indent=2, ensure_ascii=False)+'\n')
    count = sum(len(info['profiles']) for devices in report['sources'].values() for info in devices.values())
    print(f'Installed {count} profiles and bundled icons in {config}. Profile backup: {backup}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'opendeck')
    args = parser.parse_args()
    install(args.config.expanduser().resolve())
