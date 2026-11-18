#!/usr/bin/env python3
"""Select exactly one source in OBS's Loops scene via authenticated localhost WebSocket."""
import argparse
import fcntl
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def connect():
    import obsws_python
    base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'obs-studio'
    config = json.loads((base/'plugin_config/obs-websocket/config.json').read_text())
    return obsws_python.ReqClient(host='127.0.0.1', port=config.get('server_port', 4455),
                                 password=config.get('server_password', ''), timeout=5)


def items(client):
    collection = client.get_scene_collection_list().current_scene_collection_name
    if collection != 'hack.party':
        raise RuntimeError(f'Select the hack.party scene collection in OBS (current: {collection}).')
    return client.get_scene_item_list('Loops').scene_items


def toggle_exclusive(client, settings):
    """Toggle a source and clear its explicit peers, including across scenes."""
    group = settings['exclusive']
    identities = [(entry['scene'], entry['source']) for entry in group]
    identity = (settings['scene'], settings['source'])
    if len(set(identities)) != len(identities) or identities.count(identity) != 1:
        raise ValueError('Exclusive source group must contain unique sources and this key exactly once.')
    scenes = {scene: client.get_scene_item_list(scene).scene_items for scene in {s for s, _ in identities}}
    resolved = []
    for scene, source in identities:
        matching = [item for item in scenes[scene] if item['sourceName'] == source]
        if len(matching) != 1:
            raise ValueError(f'Expected exactly one {scene} source named {source!r}; found {len(matching)}.')
        resolved.append((scene, matching[0]))
    scene, target = resolved[identities.index(identity)]
    enabled = not target['sceneItemEnabled']
    # Enable the new source before hiding its peers to avoid a blank frame.
    if enabled:
        client.set_scene_item_enabled(scene, target['sceneItemId'], True)
    for peer_scene, item in resolved:
        if item['sceneItemEnabled'] and (peer_scene, item['sourceName']) != identity:
            client.set_scene_item_enabled(peer_scene, item['sceneItemId'], False)
    if not enabled:
        client.set_scene_item_enabled(scene, target['sceneItemId'], False)
    after = {scene: client.get_scene_item_list(scene).scene_items for scene in scenes}
    for peer_scene, item in resolved:
        retained = [i for i in after[peer_scene] if i['sceneItemId'] == item['sceneItemId']]
        expected = enabled and (peer_scene, item['sourceName']) == identity
        if len(retained) != 1 or retained[0]['sceneItemEnabled'] != expected:
            raise RuntimeError('OBS did not retain the exclusive source selection; check visibility automation.')


def select(client, name):
    before = items(client)
    matching = [i for i in before if i['sourceName'] == name]
    if len(matching) != 1:
        raise ValueError(f'Expected exactly one Loops source named {name!r}; found {len(matching)}.')
    target = matching[0]
    # Show the requested background before hiding others to avoid a blank frame.
    if not target['sceneItemEnabled']:
        client.set_scene_item_enabled('Loops', target['sceneItemId'], True)
    for item in before:
        if item['sceneItemId'] != target['sceneItemId'] and item['sceneItemEnabled']:
            client.set_scene_item_enabled('Loops', item['sceneItemId'], False)
    after = items(client)
    if [i['sourceName'] for i in after if i['sceneItemEnabled']] != [name]:
        raise RuntimeError('OBS did not retain the background selection; check visibility automation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', nargs='?')
    parser.add_argument('--list', action='store_true', help='Read live background names and visibility')
    args = parser.parse_args()
    if not args.list and not args.name:
        parser.error('provide a background name or --list')
    with (ROOT/'.obs-background.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with connect() as client:
            if args.list:
                print(json.dumps([{'name': i['sourceName'], 'enabled': i['sceneItemEnabled']} for i in items(client)], indent=2))
            else:
                select(client, args.name)
                print(f'Selected background: {args.name}')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'Background selection failed: {error}')
