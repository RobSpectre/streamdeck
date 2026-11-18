#!/usr/bin/env python3
"""Build, export, diagnose and install the standalone + XL laptop rig."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SERIAL = 'AD4MA61312Z98B'
SOURCE = 'opendeck-laptop.json'
PACKAGES = ['python3-venv', 'python3-yaml', 'python3-gi', 'gir1.2-atspi-2.0',
            'gir1.2-gtk-3.0', 'xdotool', 'x11-utils', 'libglib2.0-bin', 'xdg-utils',
            'zenity', 'pulseaudio-utils', 'fonts-dejavu-core', 'gnome-terminal']


def default_config():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'opendeck'


def validate_layout(data):
    if set(data['devices']) != {SERIAL}:
        raise ValueError('Laptop layout must contain only the configured + XL')
    device = data['devices'][SERIAL]
    if device.get('navigation_peer'):
        raise ValueError('Laptop navigation must be standalone')
    allowed = {'codex_telemetry', 'agent_telemetry', 'codex_response',
               'agent_action', 'codex_dictation', 'suno_media'}
    for buttons in device['buttons'].values():
        for button in buttons.values():
            kind = button.get('live_control', {}).get('kind')
            if kind and kind not in allowed:
                raise ValueError(f'Non-laptop action: {kind}')
            for state in button.get('states', {'0': button}).values():
                if any(state.get(k) for k in ('command', 'keys', 'write')) and not kind:
                    raise ValueError('Unreviewed command in laptop layout')
                target = state.get('switch_page')
                if target and str(int(target)-1) not in device['buttons']:
                    raise ValueError('Missing navigation target')
    for dials in device.get('dials', {}).values():
        for dial in dials.values():
            if dial['control'] not in {'agent', 'pc_volume', 'mic_volume', 'spotify', 'terminal_font', 'window_zoom'}:
                raise ValueError('Non-laptop dial')


def build(output, config=None):
    from tools.build_opendeck import build as generate
    validate_layout(json.loads((ROOT/SOURCE).read_text()))
    report = generate(output, ROOT, config, [ROOT/SOURCE])
    if report['warnings']:
        raise ValueError('\n'.join(report['warnings']))
    return report


def export(destination, config=None):
    """Explicit source/asset allowlist includes uncommitted work, never caches."""
    from tools.label_overrides import capture
    data = json.loads((ROOT/SOURCE).read_text())
    validate_layout(data)
    labels = json.loads((ROOT/'opendeck-labels.json').read_text())
    ids = {b.get('label_id') for bs in data['devices'][SERIAL]['buttons'].values() for b in bs.values()}
    # Read live labels without writing the desktop's overrides or profiles.
    if config:
        for path in sorted((config/'profiles'/('sd-'+SERIAL)).glob('*.json')):
            labels['labels'].update(capture(json.loads(path.read_text())))
    labels['labels'] = {k:v for k,v in labels['labels'].items() if k in ids}
    files = {Path(p) for p in ['opendeck-laptop.json', 'requirements-laptop.txt',
             'LAPTOP.md', 'agent-navigation.json', 'audio_controls.py', 'control_obs_background.py',
             'integrations/hermes-opendeck/__init__.py', 'images/fontawesome/toggle-on.png']}
    files.update(p.relative_to(ROOT) for p in (ROOT/'tools').glob('*.py'))
    def assets(value):
        if isinstance(value, dict):
            for k,v in value.items():
                if k == 'icon' and v:
                    files.add(Path(v))
                elif k == 'status_icons':
                    files.update(Path(x) for x in v)
                else:
                    assets(v)
        elif isinstance(value, list):
            for v in value:
                assets(v)
    assets(data)
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('Export already exists; choose a new filename')
    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp)/'streamdeck-laptop'
        stage.mkdir()
        for relative in sorted(files):
            source = ROOT/relative
            if relative.is_absolute() or not source.resolve().is_relative_to(ROOT) or source.is_symlink():
                raise ValueError(f'Nonportable export path: {relative}')
            dest = stage/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        (stage/'opendeck-labels.json').write_text(json.dumps(labels, indent=2)+'\n')
        hashes = {str(p.relative_to(stage)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(stage.rglob('*')) if p.is_file()}
        (stage/'export-manifest.json').write_text(json.dumps(hashes, indent=2)+'\n')
        with tarfile.open(destination, 'w:gz') as archive:
            archive.add(stage, arcname=stage.name)
    print(f'Exported {len(hashes)} files: {destination}')
    print('SHA256 '+hashlib.sha256(destination.read_bytes()).hexdigest())


def install(config):
    from tools.label_overrides import capture, apply, merge, read
    if subprocess.run(['pgrep', '-x', 'opendeck'], capture_output=True).returncode == 0:
        raise ValueError('Quit OpenDeck completely before installing')
    if not (config/'plugins/com.amansprojects.starterpack.sdPlugin').is_dir():
        raise ValueError('Install OpenDeck and its Starter Pack first')
    with tempfile.TemporaryDirectory(prefix='opendeck-laptop-') as temp:
        bundle = Path(temp)/'bundle'
        build(bundle)
        # Preserve edits already made to laptop profiles before replacing them.
        for path in (bundle/'profiles'/('sd-'+SERIAL)).glob('*.json'):
            installed = config/'profiles'/path.relative_to(bundle/'profiles')
            if installed.exists():
                merge(capture(json.loads(installed.read_text()), json.loads(path.read_text())))
        for path in (bundle/'profiles'/('sd-'+SERIAL)).glob('*.json'):
            profile = json.loads(path.read_text())
            apply(profile, read()['labels'])
            path.write_text(json.dumps(profile, indent=2)+'\n')
        backup = config.with_name(config.name+'.laptop-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copytree(config, backup)
        for name in ('profiles', 'images', 'plugins'):
            shutil.copytree(bundle/name, config/name, dirs_exist_ok=True)
        print(f'Installed laptop profiles. Full OpenDeck backup: {backup}')
        print('Start OpenDeck from your desktop session. Other named profiles were preserved.')


def doctor(config):
    failures = []
    def check(name, ok, hint):
        print(f'{"OK" if ok else "CHECK"}: {name}' + ('' if ok else ': '+hint))
        if not ok:
            failures.append(name)
    check('X11 session', os.environ.get('XDG_SESSION_TYPE') == 'x11', 'Log into an Ubuntu on Xorg session')
    for binary in ('opendeck', 'gnome-terminal', 'xdotool', 'xprop', 'gdbus', 'xdg-open', 'zenity', 'pactl'):
        check(binary, bool(shutil.which(binary)), 'Install the documented system dependencies')
    check('Starter Pack', (config/'plugins/com.amansprojects.starterpack.sdPlugin').is_dir(), 'Install through OpenDeck')
    python = ROOT/'.venv/bin/python'
    result = subprocess.run([str(python), '-c', 'import PIL, requests, websocket'], capture_output=True) if python.exists() else None
    check('Python runtime', result is not None and result.returncode == 0, 'Run bootstrap')
    result = subprocess.run(['/usr/bin/python3', '-c', "import yaml, gi; gi.require_version('Atspi','2.0'); gi.require_version('Gtk','3.0'); from gi.repository import Atspi, Gtk"], capture_output=True)
    check('System GI / AT-SPI / GTK / YAML', result.returncode == 0, 'Install the documented system dependencies')
    from tools.plusxl_touch import affected_version, find_device
    check('Known OpenDeck touch version', affected_version(), 'This rig was verified on native OpenDeck 2.14.0; verify native touch support before changing the compatibility gate')
    try:
        path = find_device()
        accessible = os.access(path, os.R_OK)
    except OSError:
        accessible = False
    check('+ XL USB read access', accessible, 'Connect AD4MA61312Z98B and configure OpenDeck USB permissions')
    for schema, key in [('org.gnome.desktop.interface', 'toolkit-accessibility'), ('org.gnome.desktop.a11y.applications', 'screen-reader-enabled')]:
        result = subprocess.run(['gsettings', 'get', schema, key], capture_output=True, text=True) if shutil.which('gsettings') else None
        check(key, result is not None and result.stdout.strip() == 'true', 'Enable GNOME accessibility as described in LAPTOP.md')
    from tools.machine_config import codex_executable
    check('Codex bundled executable', Path(codex_executable()).is_file(), 'Install Codex desktop or set portable-machine.json codex_executable')
    for agent, path in [('Claude', Path.home()/'.claude/settings.json'), ('Hermes', Path.home()/'.hermes/config.yaml')]:
        print(f'INFO: {agent} configuration {"present" if path.exists() else "absent (optional agent)"}')
    print('Read-only checks only; no approvals, playback, volumes, or model settings were changed.')
    return bool(failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=default_config())
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('export'); p.add_argument('archive', type=Path)
    p = sub.add_parser('build'); p.add_argument('--output', type=Path, required=True)
    sub.add_parser('doctor'); sub.add_parser('install'); sub.add_parser('bootstrap')
    args = parser.parse_args()
    config = args.config.expanduser().resolve()
    try:
        if args.command == 'export': export(args.archive, config)
        elif args.command == 'build': build(args.output.expanduser().resolve())
        elif args.command == 'install': install(config)
        elif args.command == 'doctor': return doctor(config)
        elif args.command == 'bootstrap':
            print('System packages (install first): sudo apt install '+' '.join(PACKAGES), flush=True)
            subprocess.run(['/usr/bin/python3', '-m', 'venv', str(ROOT/'.venv')], check=True)
            subprocess.run([str(ROOT/'.venv/bin/pip'), 'install', '-r', str(ROOT/'requirements-laptop.txt')], check=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
