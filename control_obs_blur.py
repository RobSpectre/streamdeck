#!/usr/bin/env python3
"""Blur the complete current OBS program scene; clear our filters with off."""
import argparse
import fcntl
from control_obs_background import ROOT, connect

FILTER = 'Stream Deck - Full Screen Blur'
KIND = 'obs_composite_blur'
# Plugin enums: Gaussian=1, Area=1. Zero means no valid algorithm/type.
SETTINGS = {'blur_algorithm': 1, 'blur_type': 1, 'radius': 30.0, 'effect_mask': 0}


def set_blur(client, enabled):
    if client.get_scene_collection_list().current_scene_collection_name != 'hack.party':
        raise RuntimeError('Select the hack.party scene collection in OBS.')
    scenes = client.get_scene_list()
    if enabled:
        name = scenes.current_program_scene_name
        filters = client.get_source_filter_list(name).filters
        existing = next((f for f in filters if f['filterName'] == FILTER), None)
        if existing is None:
            client.create_source_filter(name, FILTER, KIND, SETTINGS)
        elif existing['filterKind'] != KIND:
            raise RuntimeError('The managed blur filter name is already used by another filter type.')
        client.set_source_filter_settings(name, FILTER, SETTINGS, True)
        client.set_source_filter_enabled(name, FILTER, True)
        if not client.get_source_filter(name, FILTER).filter_enabled:
            raise RuntimeError('OBS did not enable the blur filter.')
        return name
    for scene in scenes.scenes:
        name = scene['sceneName']
        for f in client.get_source_filter_list(name).filters:
            if f['filterName'] == FILTER and f['filterKind'] == KIND:
                client.set_source_filter_enabled(name, FILTER, False)
                if client.get_source_filter(name, FILTER).filter_enabled:
                    raise RuntimeError(f'OBS did not disable blur on {name}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', choices=['on', 'off'])
    args = parser.parse_args()
    with (ROOT/'.obs-blur.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with connect() as client:
            scene = set_blur(client, args.state == 'on')
            print(f'Full-screen blur enabled on {scene}' if scene else 'Full-screen blur disabled')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'Blur control failed: {error}')
