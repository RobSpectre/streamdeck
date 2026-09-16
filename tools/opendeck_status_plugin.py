#!/usr/bin/env python3
"""OpenDeck plugin: OBS scene/source and Elgato light controls with live feedback."""
import argparse
import fcntl
import json
from pathlib import Path
import queue
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_obs_background import connect, select as select_background
from audio_controls import AudioControls
from tools.label_overrides import LabelSync
import requests
import websocket


def resolve_targets(targets, scenes):
    if not targets:
        raise ValueError('Effect must contain at least one target')
    resolved = []
    for target in targets:
        matching = [i for i in scenes[target['scene']] if i['sourceName'] == target['source']]
        if len(matching) != 1:
            raise ValueError(f"Missing or ambiguous effect source: {target['source']}")
        resolved.append((target['scene'], matching[0]))
    return resolved


class Controls:
    def __init__(self):
        self.obs = None
        self.audio = AudioControls()
        self.lights = json.loads((ROOT/'lights.json').read_text())

    def obs_client(self):
        if self.obs is None:
            self.obs = connect()
        return self.obs

    def reset_obs(self):
        if self.obs:
            try:
                self.obs.disconnect()
            except Exception:
                pass
        self.obs = None

    def light(self, label, enabled=None):
        url = f"http://{self.lights[label]['address']}:9123/elgato/lights"
        if enabled is None:
            response = requests.get(url, timeout=2)
        else:
            response = requests.put(url, json={'numberOfLights': 1, 'lights': [{'on': int(enabled)}]}, timeout=2)
        response.raise_for_status()
        return bool(response.json()['lights'][0]['on'])

    def snapshot(self, settings):
        result = {}
        obs_settings = [s for s in settings if s['kind'] in ('scene', 'item', 'effect', 'background')]
        if obs_settings:
            try:
                c = self.obs_client()
                if c.get_scene_collection_list().current_scene_collection_name != 'hack.party':
                    raise RuntimeError('Wrong OBS scene collection')
                current = c.get_scene_list().current_program_scene_name
                scenes = {s['scene'] for s in obs_settings if s['kind'] in ('item', 'background')}
                scenes.update(t['scene'] for s in obs_settings if s['kind'] == 'effect' for t in s['targets'])
                items = {name: c.get_scene_item_list(name).scene_items for name in scenes}
                for s in obs_settings:
                    if s['kind'] == 'scene':
                        result[s['id']] = int(current == s['scene'])
                    elif s['kind'] == 'effect':
                        try:
                            targets = resolve_targets(s['targets'], items)
                            result[s['id']] = int(any(item['sceneItemEnabled'] for scene, item in targets))
                        except ValueError:
                            result[s['id']] = 2
                    else:
                        matching = [i for i in items[s['scene']] if i['sourceName'] == s['source']]
                        result[s['id']] = int(matching[0]['sceneItemEnabled']) if len(matching) == 1 else 2
            except Exception:
                self.reset_obs()
                result.update({s['id']: 2 for s in obs_settings})
        for s in settings:
            if s['kind'] in ('audio_mode', 'mic_mute'):
                result[s['id']] = self.audio.indicator()
            elif s['kind'] == 'light':
                try:
                    result[s['id']] = int(self.light(s['light']))
                except Exception:
                    result[s['id']] = 2
        return result

    def activate(self, s):
        if s['kind'] in ('audio_mode', 'mic_mute'):
            self.audio.activate(s['kind'])
            return
        if s['kind'] == 'light':
            self.light(s['light'], not self.light(s['light']))
            return
        c = self.obs_client()
        if c.get_scene_collection_list().current_scene_collection_name != 'hack.party':
            raise RuntimeError('Select the hack.party collection in OBS')
        if s['kind'] == 'scene':
            c.set_current_program_scene(s['scene'])
            return
        if s['kind'] == 'background':
            with (ROOT/'.obs-background.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                select_background(c, s['source'])
            return
        if s['kind'] == 'effect':
            scenes = {t['scene'] for t in s['targets']}
            items = {name: c.get_scene_item_list(name).scene_items for name in scenes}
            targets = resolve_targets(s['targets'], items)
            enabled = not any(item['sceneItemEnabled'] for scene, item in targets)
            for scene, item in targets:
                if item['sceneItemEnabled'] != enabled:
                    c.set_scene_item_enabled(scene, item['sceneItemId'], enabled)
            return
        items = c.get_scene_item_list(s['scene']).scene_items
        target = next(i for i in items if i['sourceName'] == s['source'])
        enabled = not target['sceneItemEnabled']
        c.set_scene_item_enabled(s['scene'], target['sceneItemId'], enabled)
        if s.get('complement'):
            other = next(i for i in items if i['sourceName'] == s['complement'])
            c.set_scene_item_enabled(s['scene'], other['sceneItemId'], not enabled)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-port', type=int, required=True)
    parser.add_argument('-pluginUUID', required=True)
    parser.add_argument('-registerEvent', default='registerPlugin')
    parser.add_argument('-info')
    args = parser.parse_args()
    ws = websocket.create_connection(f'ws://127.0.0.1:{args.port}', timeout=5)
    ws.send(json.dumps({'event': args.registerEvent, 'uuid': args.pluginUUID}))
    ws.settimeout(None)
    events = queue.Queue()
    def receive():
        try:
            while True:
                message = ws.recv()
                if not message:
                    break
                events.put(json.loads(message))
        finally:
            events.put(None)
    threading.Thread(target=receive, daemon=True).start()
    controls = Controls()
    labels = LabelSync(lambda event: ws.send(json.dumps(event)))
    visible, last = {}, {}
    deadline = 0
    try:
        while True:
            try:
                event = events.get(timeout=max(0, deadline-time.monotonic()))
                if event is None:
                    return
                context = event.get('context')
                kind = event.get('event')
                if kind in ('willAppear', 'didReceiveSettings'):
                    visible[context] = event['payload']['settings']
                    if kind == 'willAppear':
                        labels.appear(context, event['payload']['settings'])
                    last.pop(context, None)
                    deadline = 0
                elif kind == 'willDisappear':
                    labels.disappear(context)
                    visible.pop(context, None)
                    last.pop(context, None)
                elif kind == 'titleParametersDidChange':
                    labels.changed(context, event['payload'])
                elif kind == 'keyDown' and context in visible:
                    try:
                        controls.activate(visible[context])
                    except Exception as error:
                        print(f"Control {visible[context].get('id')} failed: {type(error).__name__}", flush=True)
                        controls.reset_obs()
                        ws.send(json.dumps({'event': 'showAlert', 'context': context}))
                    deadline = 0
            except queue.Empty:
                if visible:
                    states = controls.snapshot(list({s['id']:s for s in visible.values()}.values()))
                    for context, settings in visible.items():
                        state = states.get(settings['id'], 2)
                        if last.get(context) != state:
                            ws.send(json.dumps({'event': 'setState', 'context': context, 'payload': {'state': state}}))
                            last[context] = state
                deadline = time.monotonic()+1
    finally:
        controls.reset_obs()
        ws.close()


if __name__ == '__main__':
    main()
