"""Read actual volume settings and route physical encoder rotations."""
import base64
from functools import lru_cache
import io
import json
import math
from pathlib import Path
import subprocess
from PIL import Image

from tools.f1_battles import (GAP_LIMIT_MAX, GAP_LIMIT_MIN, GAP_LIMIT_STEP,
                              gap_limit, set_gap_limit)

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.check_output(args, text=True, timeout=4, stderr=subprocess.DEVNULL)


def clamp(value, low=0, high=100):
    if not math.isfinite(value):
        raise ValueError('Nonfinite dial value')
    return max(low, min(high, value))


@lru_cache(maxsize=2)
def background(muted):
    buffer = io.BytesIO()
    Image.new('RGB', (200, 100), '#a51f32' if muted else '#10141b').save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


@lru_cache(maxsize=1)
def blank_background():
    buffer = io.BytesIO()
    Image.new('RGB', (200, 100), '#000000').save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def feedback(title, value=None, unit='%', muted=False, detail='', meter=None, decimals=0):
    result = {'title': title, 'background': background(muted)}
    if value is None:
        return {**result, 'value': '—', 'indicator': 0, 'detail': detail or 'UNAVAILABLE'}
    if meter is None:
        meter = (clamp(value, -60, 0) + 60) / 60 * 100 if unit == 'dB' else clamp(value)
    return {**result, 'value': ('−∞dB' if unit == 'dB' else '0%') if muted else f'{value:.{decimals}f}{unit}',
            'indicator': 0 if muted else meter,
            'detail': 'MUTED' if muted else detail or 'VOLUME'}


class Dials:
    def __init__(self, obs_client, agent_dials=None, battle_visible=None):
        self.obs_client = obs_client
        self.agent_dials = agent_dials
        self.battle_visible = battle_visible or (lambda: True)

    def pulse_target(self, kind):
        info = json.loads(run('pactl', '-f', 'json', 'info'))
        target = info['default_sink_name' if kind == 'pc_volume' else 'default_source_name']
        devices = json.loads(run('pactl', '-f', 'json', 'list', 'sinks' if kind == 'pc_volume' else 'sources'))
        matches = [d for d in devices if d['name'] == target]
        if len(matches) != 1 or (kind == 'mic_volume' and target.endswith('.monitor')):
            raise ValueError('Missing or ambiguous default audio device')
        d = matches[0]
        value = max(float(v['value']) / 65536 * 100 for v in d['volume'].values())
        clamp(value)
        return d, value

    def gap_limit_feedback(self, title):
        """The battle-width strip, in the shape the volume meters use."""
        value = gap_limit()
        span = (value - GAP_LIMIT_MIN) / (GAP_LIMIT_MAX - GAP_LIMIT_MIN) * 100
        result = feedback(title, value, 's', detail='BATTLE WIDTH', meter=span, decimals=1)
        result['indicator'] = {'value': span, 'enabled': True}
        return result

    def read(self, settings):
        kind, title = settings['control'], settings['title']
        if kind == 'f1_gap_limit':
            if not self.battle_visible():
                return {'title': '', 'value': '', 'indicator': {'value': 0, 'enabled': False}, 'detail': '',
                        'background': blank_background()}
            return self.gap_limit_feedback(title)
        if kind in ('pc_volume', 'mic_volume'):
            d, value = self.pulse_target(kind)
            return feedback(title, value, muted=d['mute'])
        if kind == 'obs_volume':
            obs = self.obs_client()
            if obs.get_scene_collection_list().current_scene_collection_name != 'hack.party':
                raise ValueError('Wrong OBS collection')
            value = float(obs.get_input_volume(settings['input']).input_volume_db)
            return feedback(title, value, 'dB', obs.get_input_mute(settings['input']).input_muted)
        result = json.loads(run('/usr/bin/python3', str(ROOT/'tools/dial_desktop.py'), kind))
        streams = self.spotify_streams() if kind == 'spotify' else []
        return feedback(title, result['value'], muted=bool(streams) and all(d['mute'] for d in streams),
                        detail=result.get('detail', ''))

    def snapshot(self, settings):
        result = {}
        agents = [s for s in settings if s.get('control') == 'agent']
        if agents and self.agent_dials:
            result.update(self.agent_dials.snapshot(agents))
        for s in settings:
            if s.get('control') == 'agent':
                continue
            try:
                result[s['id']] = self.read(s)
            except Exception:
                result[s['id']] = feedback(s['title'])
        return result

    def spotify_streams(self):
        streams = json.loads(run('pactl', '-f', 'json', 'list', 'sink-inputs'))
        clients = json.loads(run('pactl', '-f', 'json', 'list', 'clients'))
        by_client = {}
        for client in clients:
            identity = str(client['index'])
            if identity in by_client:
                raise ValueError('Ambiguous audio client')
            by_client[identity] = client.get('properties', {})
        matched, owners = [], set()
        for stream in streams:
            props = stream.get('properties', {})
            client = by_client.get(str(stream.get('client')), {})
            # Native PipeWire keeps process metadata on the client; PulseAudio
            # streams can carry it themselves. Do not infer identity from titles.
            binary = client.get('application.process.binary', props.get('application.process.binary', ''))
            pid = client.get('pipewire.sec.pid') or client.get('application.process.id') or props.get('application.process.id')
            if binary.lower() != 'spotify':
                continue
            if not pid or not str(pid).isdecimal():
                raise ValueError('Missing Spotify audio owner')
            matched.append(stream)
            owners.add(str(pid))
        if len(owners) > 1:
            raise ValueError('Ambiguous Spotify audio owner')
        return matched

    def tap(self, settings, hold=False):
        # A long press is not another mute gesture. Non-audio sections are inert.
        if hold:
            return
        kind = settings['control']
        if kind == 'agent':
            return self.agent_dials.tap(settings)
        if kind in ('pc_volume', 'mic_volume'):
            device, _ = self.pulse_target(kind)
            run('pactl', 'set-sink-mute' if kind == 'pc_volume' else 'set-source-mute',
                device['name'], 'toggle')
        elif kind == 'obs_volume':
            obs = self.obs_client()
            if obs.get_scene_collection_list().current_scene_collection_name != 'hack.party':
                raise ValueError('Wrong OBS collection')
            obs.toggle_input_mute(settings['input'])
        elif kind == 'spotify':
            streams = self.spotify_streams()
            if not streams:
                raise ValueError('No Spotify audio stream')
            # Preserve Spotify's volume; mute its audio streams at the sound server.
            muted = not all(d['mute'] for d in streams)
            for stream in streams:
                run('pactl', 'set-sink-input-mute', str(stream['index']), str(int(muted)))

    def rotate(self, settings, ticks):
        if isinstance(ticks, bool) or not isinstance(ticks, int) or not -100 <= ticks <= 100:
            raise ValueError('Invalid encoder ticks')
        if not ticks:
            return
        kind = settings['control']
        if kind == 'agent':
            return self.agent_dials.rotate(settings, ticks)
        if kind == 'f1_gap_limit':
            if not self.battle_visible():
                return
            # Answer the twist with feedback straight away rather than leaving the
            # strip a poll behind the knob.
            set_gap_limit(gap_limit() + ticks * GAP_LIMIT_STEP)
            return {settings['id']: self.gap_limit_feedback(settings['title'])}
        if kind in ('pc_volume', 'mic_volume'):
            device, value = self.pulse_target(kind)
            target = clamp(value + ticks * 2)
            # Bind the write to the resolved device name, not a changing default.
            run('pactl', 'set-sink-volume' if kind == 'pc_volume' else 'set-source-volume',
                device['name'], f'{target:.3f}%')
        elif kind == 'obs_volume':
            obs = self.obs_client()
            if obs.get_scene_collection_list().current_scene_collection_name != 'hack.party':
                raise ValueError('Wrong OBS collection')
            value = float(obs.get_input_volume(settings['input']).input_volume_db)
            obs.set_input_volume(settings['input'], vol_db=clamp(value + ticks, -100, 0))
        else:
            run('/usr/bin/python3', str(ROOT/'tools/dial_desktop.py'), kind, str(ticks))
