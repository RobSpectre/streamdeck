#!/usr/bin/env python3
"""OpenDeck plugin: OBS scene/source and Elgato light controls with live feedback."""
import argparse
import base64
import fcntl
import json
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_obs_background import connect, select as select_background, toggle_exclusive
from audio_controls import AudioControls
from tools.label_overrides import LabelSync
from tools.dial_controls import Dials
from tools import chyron_capsules
from tools import hermes_config
from tools.telemetry_graphs import GraphHistory
from tools.agent_dials import AgentDials
from tools.plusxl_touch import TouchReader, forwardable
from tools.codex_attention import CodexAttention
from tools.codex_pedal import respond as codex_respond
from tools.codex_pedal import codex_focused, dictate
from tools.cli_agent_bridge import auto_enabled, disable_auto, respond_focused
from tools.codex_telemetry import Telemetry, render as render_telemetry, animation_phase
from tools.agent_telemetry import AgentTelemetry
from tools.agent_presence import Presence
from tools.agent_navigation import activate as navigate_agent
from tools.agent_compact import compact as compact_agent
from tools.cli_agent_bridge import pending as cli_pending
from tools.f1_battles import BattleFeed, F1BattleError
from tools.f1_battles import render as render_battle
from tools import f1_keys
from tools import track_status
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


def theme_image(theme):
    """The key art for one look, as the data URL the app takes, or None.

    The tiles are drawn by the overlay repo (`scripts/make_deck_icons.py`, from the
    look's own colours in its stylesheet) into this repo's images/controls, so the
    plugin only has to find the file a theme's name points at - which is why it can
    show a look it has never heard of, and why adding a look needs no plugin change
    beyond a new file landing in that directory.
    """
    if not theme:
        return None
    path = ROOT/'images/controls'/f'theme-{theme}.png'
    if not path.is_file():
        return None
    return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()


def track_image(settings, status):
    """The image to send for one track-status key, or None if it is not one.

    A key is drawn from its own art with the status drawn over it, and a clear
    track sends that art plain. It is sent as soon as the key's page is shown
    rather than only after a status has been seen, because the app keeps the last
    image a key was sent: a deck restarted under a flag would otherwise hold a
    stale mark until the next one.
    """
    art = settings.get('_track_status')
    if not art:
        return None
    return track_status.key_image(art, status)


class Controls:
    def __init__(self):
        self.obs = None
        self.audio = AudioControls()
        self.codex = None
        self.telemetry = None
        self.agents = None
        self.presence = None
        self.f1 = None
        self.dials = None
        self.lights = json.loads((ROOT/'lights.json').read_text()) if (ROOT/'lights.json').exists() else {}
        # The look each theme key is on, filled by snapshot() and read by the poll
        # loop to set that key's image and title. A side channel rather than part of
        # snapshot's return value, which is a plain {id: state} every other kind and
        # the tests rely on.
        self.themes = {}

    def battle_feed(self):
        if self.f1 is None:
            self.f1 = BattleFeed()
        return self.f1

    def f1_visibility(self, settings):
        """Monitoring follows native visible page contexts, including the dial."""
        shown = any(s.get('_track_status') or s.get('kind') in ('f1_key', 'f1_battle') or
                    s.get('control') == 'f1_gap_limit' for s in settings)
        if not shown and self.f1 is not None:
            self.f1.pause()
        return shown

    def battle_dial_visible(self):
        return self.f1 is not None and self.f1.available and self.f1.mode == 'race'

    def theme_of(self, source):
        """The look the overlay is on, read out of the source URL OBS is holding.

        The URL is the truth rather than a copy of it: the cycle writes it, the page
        reads it, and a look set by hand shows up on the key too. One source is
        enough - the pass that changes a theme changes all three together.
        """
        settings = self.obs_client().get_input_settings(source).input_settings
        query = parse_qs(urlparse(settings.get('url') or '').query)
        return (query.get('theme') or [''])[0]

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
        if self.f1_visibility(settings):
            self.battle_feed().value()
        battle_keys = [s for s in settings if s['kind'] == 'f1_battle']
        if battle_keys:
            for s in battle_keys:
                result[s['id']] = 0 if self.battle_feed().slot(s.get('slot', 0))[0] in ('battle', 'flying') else 1
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
        obs_settings = [s for s in settings if s['kind'] in ('scene', 'item', 'effect', 'background', 'theme', 'chyron_capsule')]
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
                    elif s['kind'] == 'chyron_capsule':
                        try:
                            result[s['id']] = int(chyron_capsules.enabled(c, s))
                        except (ValueError, KeyError):
                            result[s['id']] = 2
                    elif s['kind'] == 'theme':
                        theme = self.theme_of(s['source'])
                        self.themes[s['id']] = theme
                        result[s['id']] = 1 if theme else 2
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
            if s['kind'] == 'dial_view':
                result[s['id']] = int(bool(self.dials and self.dials.audio_view == s['view']))
            elif s['kind'] == 'hermes_config':
                # Which profile a bare `hermes` launch will use: the key is the mode
                # indicator, and pressing it is the same switch a hand-run makes.
                result[s['id']] = hermes_config.state()
            elif s['kind'] == 'suno_media':
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
        if s['kind'] == 'dial_view':
            self.dials.select_view(s['view'])
            return
        if s['kind'] == 'f1_battle':
            # The key selects the driver it is showing, so the press reads the
            # cached slot rather than refreshing into a different driver. It goes
            # through the same call as the XL's driver selectors, so a driver
            # behaves the same way whichever deck picked them.
            value = self.battle_feed().slot(s.get('slot', 0))
            if value[0] not in ('battle', 'flying'):
                raise F1BattleError('No live driver on this key')
            f1_keys.driver(value[1])
            return
        if s['kind'] == 'f1_key':
            f1_keys.run(s.get('command', ''))
            return
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
            agent = 'codex' if s['kind'] == 'codex_telemetry' else s['agent']
            if s['metric'] == 'context':
                compact_agent(agent, self.codex)
            else:
                navigate_agent(agent, s['metric'])
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
        if s['kind'] == 'hermes_config':
            hermes_config.toggle()
            return
        c = self.obs_client()
        if c.get_scene_collection_list().current_scene_collection_name != 'hack.party':
            raise RuntimeError('Select the hack.party collection in OBS')
        if s['kind'] == 'chyron_capsule':
            chyron_capsules.toggle(c, s)
            return
        if s['kind'] == 'theme':
            # The same script a hand-run uses, so the key and the terminal cannot
            # drift: it cycles from the URLs OBS is holding and refreshes the sources.
            # The app turns the raise into its own alert.
            subprocess.run([sys.executable, s['script'], '--theme', 'next'],
                           check=True, timeout=30)
            return
        if s['kind'] == 'scene':
            c.set_current_program_scene(s['scene'])
            return
        if s.get('exclusive'):
            with (ROOT/'.obs-background.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                toggle_exclusive(c, s)
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
    touch_reader = TouchReader(events)
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
    def dial_codex():
        if controls.codex is None:
            controls.codex = CodexAttention(controls.presence)
        return controls.codex
    dials = Dials(controls.obs_client, AgentDials(dial_codex), controls.battle_dial_visible)
    controls.dials = dials
    dial_values = {}
    labels = LabelSync(lambda event: ws.send(json.dumps(event)))
    visible, last, last_images = {}, {}, {}
    deadline = 0
    next_poll = 0
    states, sources = {}, {}
    activity_log = {}
    f1_log = None
    graphs = None
    graph_series = {}
    try:
        while True:
            try:
                event = events.get(timeout=max(0, deadline-time.monotonic()))
                if event is None:
                    return
                context = event.get('context')
                kind = event.get('event')
                if kind == 'plusXLTouch':
                    if forwardable(event, visible, time.monotonic()):
                        ws.send(json.dumps({'event': 'touchscreenPress', 'payload': event['payload']}))
                    continue
                if kind in ('willAppear', 'didReceiveSettings'):
                    visible[context] = event['payload']['settings']
                    if kind == 'willAppear' and event['payload']['settings'].get('kind') == 'dial':
                        print(f"Dial visible: {event['payload']['settings']['control']}", flush=True)
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
                elif kind in ('dialRotate', 'touchTap', 'dialDown') and context in visible:
                    try:
                        if visible[context].get('kind') != 'dial':
                            raise ValueError('Not a dial context')
                        if kind == 'dialDown':
                            dials.press(visible[context])
                        elif kind == 'touchTap':
                            print(f"Touch tap received: {visible[context]['control']} hold={event['payload'].get('hold', False)}", flush=True)
                            dials.tap(visible[context], event['payload'].get('hold', False))
                        else:
                            immediate = dials.rotate(visible[context], event['payload']['ticks'])
                            if immediate:
                                for dial_context, dial_settings in visible.items():
                                    value = immediate.get(dial_settings.get('id'))
                                    if value is not None and last_images.get(dial_context) != value:
                                        ws.send(json.dumps({'event': 'setFeedback', 'context': dial_context, 'payload': value}))
                                        last_images[dial_context] = value
                    except Exception as error:
                        print(f"Dial {visible[context].get('id')} failed: {type(error).__name__}", flush=True)
                        controls.reset_obs()
                        ws.send(json.dumps({'event': 'showAlert', 'context': context}))
                    deadline = 0
                    next_poll = 0
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
                controls.f1_visibility(visible.values())
            except queue.Empty:
                animated = False
                if visible:
                    now = time.monotonic()
                    if now >= next_poll:
                        states = controls.snapshot(list({s['id']:s for s in visible.values()}.values()))
                        if controls.f1 is not None:
                            monitor = (controls.f1.available, controls.f1.mode)
                            if f1_log != monitor:
                                print(f'F1 monitor: api={monitor[0]} mode={monitor[1]}', flush=True)
                                f1_log = monitor
                        dial_values = dials.snapshot([s for s in visible.values() if s['kind'] == 'dial'])
                        shown = {s.get('agent', 'codex') for s in visible.values()
                                 if s['kind'] in ('codex_telemetry', 'agent_telemetry')}
                        samples = {agent: {} for agent in shown}
                        sources = {'codex': controls.telemetry.values(samples['codex']) if controls.telemetry and 'codex' in shown else {}}
                        if controls.agents:
                            sources.update({agent: controls.agents.values(agent, samples[agent]) for agent in ('claude', 'hermes') if agent in shown})
                        if shown:
                            try:
                                if graphs is None:
                                    graphs = GraphHistory()
                                wall_time = time.time()
                                for agent in shown:
                                    graphs.observe(agent, samples[agent], wall_time)
                                graph_series = {(agent, metric): graphs.series(agent, metric, wall_time)
                                                for agent in shown for metric in ('speed', 'context', 'session', 'month')}
                            except (OSError, sqlite3.Error):
                                graph_series = {}  # Cache failure must not blank live telemetry.
                        for agent in shown:
                            activity = sources.get(agent, {}).get('activity')
                            status = (controls.presence.is_open(agent), activity[1] if activity else 'UNAVAILABLE')
                            if activity_log.get(agent) != status:
                                print(f'Agent status: {agent} present={status[0]} activity={status[1]}', flush=True)
                                activity_log[agent] = status
                        next_poll = time.monotonic()+1
                    # The Formula 1 page wears the race director's status, so it is
                    # read once a second while any of its keys is up, or while a
                    # battle card is (which carries the flag in its own art).
                    race_status = controls.f1.track_status if controls.f1 else track_status.CLEAR
                    for context, settings in visible.items():
                        if settings['kind'] == 'dial':
                            value = dial_values.get(settings['id'])
                            if value is not None and last_images.get(context) != value:
                                ws.send(json.dumps({'event': 'setFeedback', 'context': context, 'payload': value}))
                                last_images[context] = value
                            continue
                        if settings['kind'] in ('codex_telemetry', 'agent_telemetry'):
                            source = sources.get('codex' if settings['kind'] == 'codex_telemetry' else settings['agent'], {})
                            value = source.get(settings['metric'])
                            phase = animation_phase(value, now) if value is not None else None
                            history = graph_series.get(('codex' if settings['kind'] == 'codex_telemetry' else settings['agent'], settings['metric']), ())
                            animated = animated or phase is not None
                            frame = (value, phase, history)
                            if value is not None and last_images.get(context) != frame:
                                ws.send(json.dumps({'event': 'setImage', 'context': context,
                                                    'payload': {'image': render_telemetry(value, phase, history), 'target': 0}}))
                                if settings['metric'] == 'quota' and (context not in last_images or last_images[context][0] != value):
                                    agent = 'codex' if settings['kind'] == 'codex_telemetry' else settings['agent']
                                    print(f'Quota image sent: {agent} value={value[1]} context={context}', flush=True)
                                last_images[context] = frame
                            continue
                        if settings['kind'] == 'f1_battle':
                            value = (controls.battle_feed().slot(settings.get('slot', 0)), race_status)
                            if last_images.get(context) != value:
                                ws.send(json.dumps({'event': 'setImage', 'context': context,
                                                    'payload': {'image': render_battle(value[0], race_status),
                                                                'target': 0}}))
                                last_images[context] = value
                            continue
                        if settings.get('_track_status'):
                            # The key's own art, with the race director's status
                            # drawn on it while there is one.
                            image = track_image(settings, race_status)
                            if image is not None and last_images.get(context) != image:
                                ws.send(json.dumps({'event': 'setImage', 'context': context,
                                                    'payload': {'image': image, 'target': 0}}))
                                last_images[context] = image
                            continue
                        if settings['kind'] == 'theme':
                            # The look this key is on. The title is ours (the theme's
                            # name), so the key is kept out of the label sync in
                            # label_overrides - otherwise the app would report our own
                            # title back as a user edit and pin it.
                            theme = controls.themes.get(settings['id'])
                            if last_images.get(context) != theme:
                                image = theme_image(theme)
                                if image:
                                    ws.send(json.dumps({'event': 'setImage', 'context': context,
                                                        'payload': {'image': image, 'target': 0}}))
                                title = theme.capitalize() if theme else settings.get(
                                    '_label_defaults', ['Theme'])[0]
                                ws.send(json.dumps({'event': 'setTitle', 'context': context,
                                                    'payload': {'title': title}}))
                                last_images[context] = theme
                            continue
                        state = states.get(settings['id'], 2)
                        if last.get(context) != state:
                            ws.send(json.dumps({'event': 'setState', 'context': context, 'payload': {'state': state}}))
                            last[context] = state
                deadline = time.monotonic()+(.125 if animated else 1)
    finally:
        if graphs is not None:
            graphs.close()
        touch_reader.close()
        controls.presence.close()
        controls.reset_obs()
        ws.close()


if __name__ == '__main__':
    main()
