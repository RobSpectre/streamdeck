#!/usr/bin/env python3
"""OpenDeck plugin: OBS scene/source and Elgato light controls with live feedback."""
import argparse
import fcntl
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_obs_background import connect, select as select_background
from audio_controls import AudioControls
from tools.label_overrides import LabelSync
from tools.codex_attention import CodexAttention
from tools.codex_pedal import respond as codex_respond
from tools.codex_pedal import codex_focused, dictate
from tools.cli_agent_bridge import auto_enabled, disable_auto, respond_focused
from tools.codex_telemetry import Telemetry, render as render_telemetry, animation_phase
from tools.agent_telemetry import AgentTelemetry
from tools.agent_presence import Presence
from tools.agent_navigation import activate as navigate_agent
from tools.cli_agent_bridge import pending as cli_pending
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
        self.codex = None
        self.telemetry = None
        self.agents = None
        self.presence = None
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
        if any(s['kind'] == 'agent_telemetry' for s in settings) and self.agents is None:
            self.agents = AgentTelemetry(self.presence)
        codex_settings = [s for s in settings if s['kind'] in ('codex_response', 'codex_telemetry', 'agent_action')]
        if codex_settings:
            if self.codex is None:
                self.codex = CodexAttention(self.presence)
            cli_requests = cli_pending()
            state = int(bool(self.codex.indicator() or cli_requests))
            result.update({s['id']: state for s in codex_settings})
            for s in codex_settings:
                if s['kind'] == 'agent_action':
                    ready = len(self.codex.actionable()) == 1 or any(
                        p.get('extended') and (s['decision'] != 'allow_tool' or p.get('allow_tool'))
                        for p in cli_requests)
                    result[s['id']] = 2 if s['decision'] == 'auto' and (self.codex.auto_thread or auto_enabled()) else int(ready)
            if any(s['kind'] == 'codex_telemetry' for s in settings) and self.telemetry is None:
                self.telemetry = Telemetry(self.codex, self.presence)
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
            if s['kind'] == 'suno_media':
                result[s['id']] = 0
            elif s['kind'] == 'codex_dictation':
                result[s['id']] = int(bool(codex_focused()))
            elif s['kind'] in ('audio_mode', 'mic_mute'):
                result[s['id']] = self.audio.indicator()
            elif s['kind'] == 'light':
                try:
                    result[s['id']] = int(self.light(s['light']))
                except Exception:
                    result[s['id']] = 2
        return result

    def activate(self, s):
        if s['kind'] == 'suno_media':
            subprocess.run(['/usr/bin/python3', str(ROOT/'tools/suno_media.py'), s['action']],
                           check=True, timeout=12)
            return
        if s['kind'] == 'codex_dictation':
            dictate()
            return
        if s['kind'] == 'agent_action':
            if s['decision'] == 'auto' and (auto_enabled() or self.codex and self.codex.auto_thread):
                disable_auto()
                if self.codex:
                    self.codex.auto_thread = None
                return
            window = subprocess.check_output(['xdotool', 'getactivewindow'], text=True).strip()
            identity = subprocess.check_output(['xprop', '-id', window, '_NET_WM_NAME', '_NET_WM_PID'], text=True)
            if respond_focused(s['decision'], window, identity):
                return
            if self.codex and codex_focused() == window:
                self.codex.extended_action(s['decision'])
            return
        if s['kind'] in ('codex_telemetry', 'agent_telemetry'):
            navigate_agent('codex' if s['kind'] == 'codex_telemetry' else s['agent'], s['metric'])
            return
        if s['kind'] == 'codex_response':
            if (self.codex and self.codex.indicator()) or cli_pending():
                codex_respond(s['decision'], codex_ready=bool(self.codex and self.codex.indicator()))
            return
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
    controls.presence = Presence()
    labels = LabelSync(lambda event: ws.send(json.dumps(event)))
    visible, last, last_images = {}, {}, {}
    deadline = 0
    next_poll = 0
    states, sources = {}, {}
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
                    last_images.pop(context, None)
                    deadline = 0
                    next_poll = 0
                elif kind == 'willDisappear':
                    labels.disappear(context)
                    visible.pop(context, None)
                    last.pop(context, None)
                    last_images.pop(context, None)
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
                    next_poll = 0
                controls.presence.show({
                    'codex' if s['kind'] == 'codex_telemetry' else s['agent']
                    for s in visible.values() if s['kind'] in ('codex_telemetry', 'agent_telemetry')})
            except queue.Empty:
                animated = False
                if visible:
                    now = time.monotonic()
                    if now >= next_poll:
                        states = controls.snapshot(list({s['id']:s for s in visible.values()}.values()))
                        shown = {s.get('agent', 'codex') for s in visible.values()
                                 if s['kind'] in ('codex_telemetry', 'agent_telemetry')}
                        sources = {'codex': controls.telemetry.values() if controls.telemetry and 'codex' in shown else {}}
                        if controls.agents:
                            sources.update({agent: controls.agents.values(agent) for agent in ('claude', 'hermes') if agent in shown})
                        next_poll = time.monotonic()+1
                    for context, settings in visible.items():
                        if settings['kind'] in ('codex_telemetry', 'agent_telemetry'):
                            source = sources.get('codex' if settings['kind'] == 'codex_telemetry' else settings['agent'], {})
                            value = source.get(settings['metric'])
                            phase = animation_phase(value, now) if value is not None else None
                            animated = animated or phase is not None
                            frame = (value, phase)
                            if value is not None and last_images.get(context) != frame:
                                ws.send(json.dumps({'event': 'setImage', 'context': context,
                                                    'payload': {'image': render_telemetry(value, phase), 'target': 0}}))
                                last_images[context] = frame
                            continue
                        state = states.get(settings['id'], 2)
                        if last.get(context) != state:
                            ws.send(json.dumps({'event': 'setState', 'context': context, 'payload': {'state': state}}))
                            last[context] = state
                deadline = time.monotonic()+(.125 if animated else 1)
    finally:
        controls.presence.close()
        controls.reset_obs()
        ws.close()


if __name__ == '__main__':
    main()
