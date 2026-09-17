"""Local Codex usage accounting and Stream Deck telemetry images."""
import base64
from contextlib import closing
from datetime import datetime
import io
import json
from pathlib import Path
import select
import sqlite3
import subprocess
import threading
import time
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont
from tools.codex_attention import needs_input

CODEX = Path.home()/'.codex'
MONTH = 30 * 86400


def compact(value):
    if value is None:
        return '—'
    for divisor, suffix in [(1e9, 'B'), (1e6, 'M'), (1e3, 'K')]:
        if value >= divisor:
            return f'{value/divisor:.1f}{suffix}'
    return str(int(value))


def quota_window(limits, now):
    bucket = limits.get('rateLimitsByLimitId', {}).get('codex') or limits.get('rateLimits') or {}
    windows = [bucket[k] for k in ['primary', 'secondary'] if bucket.get(k)]
    windows = [w for w in windows if w.get('usedPercent') is not None and w.get('resetsAt', 0) > now]
    if not windows:
        return None, None, None
    limiting = max(windows, key=lambda w: w['usedPercent'])
    weekly = next((w for w in windows if w.get('windowDurationMins') == 10080), limiting)
    start = weekly['resetsAt'] - weekly.get('windowDurationMins', 0) * 60
    return max(0, min(100, 100-limiting['usedPercent'])), max(0, (now-start)/86400), limiting.get('windowDurationMins')


def read_quota():
    """Query account quota without creating a thread or redeeming a reset."""
    proc = subprocess.Popen(['/usr/lib/chatgpt/resources/codex', 'app-server', '--stdio'],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    buffer = bytearray()
    def request(message):
        proc.stdin.write((json.dumps(message)+'\n').encode())
        proc.stdin.flush()
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            if b'\n' not in buffer:
                if not select.select([proc.stdout], [], [], max(0, deadline-time.monotonic()))[0]:
                    break
                import os
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer.extend(chunk)
            while b'\n' in buffer:
                line, _, rest = buffer.partition(b'\n')
                buffer[:] = rest
                reply = json.loads(line)
                if reply.get('id') == message['id']:
                    if 'error' in reply:
                        raise RuntimeError(reply['error'])
                    return reply['result']
        raise TimeoutError('Codex quota read timed out')
    try:
        request({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'opendeck_telemetry', 'version': '1.0'}}})
        proc.stdin.write(b'{"method":"initialized"}\n')
        proc.stdin.flush()
        return request({'id': 2, 'method': 'account/rateLimits/read'})
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdin.close()
        proc.stdout.close()


class RolloutUsage:
    def __init__(self, path, created):
        self.path, self.created = Path(path), created
        self.offset = 0
        self.previous = None
        self.events = []
        self.turn_start = None
        self.turn_output = 0
        self.turn_end = None

    def update(self):
        if self.path.stat().st_size < self.offset:
            self.__init__(self.path, self.created)
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            while True:
                line = stream.readline()
                if not line or not line.endswith(b'\n'):
                    break
                self.offset = stream.tell()
                try:
                    event = json.loads(line)
                    if event.get('type') != 'event_msg':
                        continue
                    payload = event['payload']
                    stamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')).timestamp()
                    kind = payload.get('type')
                    if kind == 'task_started':
                        self.turn_start = payload.get('started_at', stamp)
                        self.turn_output, self.turn_end = 0, None
                    elif kind in ('task_complete', 'turn_aborted'):
                        self.turn_end = payload.get('completed_at', stamp)
                    elif kind == 'token_count' and payload.get('info'):
                        info = payload['info']
                        total = info['total_token_usage']['total_tokens']
                        output = info['total_token_usage']['output_tokens']
                        if self.previous is None or total < self.previous[0]:
                            # First counters can include inherited history from a fork.
                            delta = info.get('last_token_usage', {}).get('total_tokens', 0)
                            output_delta = info.get('last_token_usage', {}).get('output_tokens', 0)
                        else:
                            delta, output_delta = total-self.previous[0], max(0, output-self.previous[1])
                        self.previous = total, output
                        if stamp >= self.created and delta > 0:
                            self.events.append((stamp, delta))
                            self.turn_output += output_delta
                except (ValueError, KeyError, TypeError):
                    continue

    def speed(self, now):
        if self.turn_start is None:
            return None
        return self.turn_output/max(1, (self.turn_end or now)-self.turn_start)


class Telemetry:
    def __init__(self, attention, presence=None):
        self.attention = attention
        self.presence = presence
        self.lock = threading.Lock()
        self.monthly = None
        self.readers = {}
        self.thread_stats = {}
        self.limits = {}
        self.quota_at = 0
        threading.Thread(target=self.scan, daemon=True).start()
        threading.Thread(target=self.poll_quota, daemon=True).start()

    def scan(self):
        delay = 0
        while True:
            if self.presence and not self.presence.wait('codex', delay):
                return
            try:
                now = time.time()
                with closing(sqlite3.connect((CODEX/'state_5.sqlite').as_uri()+'?mode=ro', uri=True)) as db:
                    rows = db.execute('SELECT id, rollout_path, created_at FROM threads WHERE updated_at >= ?', (now-MONTH,)).fetchall()
                totals, stats = 0, {}
                for thread, path, created in rows:
                    reader = self.readers.setdefault(thread, RolloutUsage(path, created))
                    try:
                        reader.update()
                    except OSError:
                        continue
                    reader.events = [(t, n) for t, n in reader.events if t >= now-MONTH]
                    totals += sum(n for _, n in reader.events)
                    stats[thread] = (reader.speed(now), reader.previous[0] if reader.previous else None)
                with self.lock:
                    self.monthly, self.thread_stats = totals, stats
            except (sqlite3.Error, OSError):
                with self.lock:
                    self.monthly = None
            delay = 2
            if not self.presence:
                time.sleep(delay)

    def poll_quota(self):
        delay = 0
        while True:
            if self.presence and not self.presence.wait('codex', delay):
                return
            try:
                limits = read_quota()
                with self.lock:
                    self.limits, self.quota_at = limits, time.time()
            except (OSError, ValueError, RuntimeError, TimeoutError):
                pass
            delay = 60
            if not self.presence:
                time.sleep(delay)

    def values(self):
        now = time.time()
        connected, states = self.attention.snapshot()
        offline = self.presence is not None and not self.presence.is_open('codex')
        if offline:
            connected, states = False, {}
        thread, current = max(states.items(), key=lambda item: (
            item[1].get('threadRuntimeStatus', {}).get('type') == 'active', item[1].get('updatedAt', 0)), default=(None, {}))
        active = any(s.get('threadRuntimeStatus', {}).get('type') == 'active' for s in states.values())
        waiting = connected and any(needs_input(s) for s in states.values())
        with self.lock:
            monthly = self.monthly
            speed, fallback = self.thread_stats.get(thread, (None, None))
            limits = self.limits if not offline and now-self.quota_at < 180 else {}
        tokens = (current.get('latestTokenUsageInfo') or {}).get('total', {}).get('totalTokens', fallback)
        quota, days, duration = quota_window(limits, now)
        usage = current.get('latestTokenUsageInfo') or {}
        context = context_left(usage.get('last', {}).get('totalTokens'), usage.get('modelContextWindow'))
        color = '#ffffff'
        return {
            'activity': ('', 'WAITING' if waiting else 'ACTIVE' if active else 'IDLE' if connected else 'OFFLINE', model_label(current.get('latestModel')), color),
            'speed': ('TOKENS / SEC', f'{speed:.1f}' if speed is not None else '—', 'TURN AVG · OUTPUT', color),
            'session': ('SESSION TOKENS', compact(tokens), 'CURRENT TASK', color),
            'month': ('30-DAY TOKENS', compact(monthly), 'CACHED · LOCAL' if offline else 'THIS COMPUTER', color),
            'quota': ('QUOTA LEFT', f'{quota:.0f}%' if quota is not None else '—',
                      'WEEKLY' if duration == 10080 else 'LIMITING WINDOW', color),
            'context': ('CONTEXT LEFT', context, 'CURRENT TASK', color),
        }


def context_left(used, limit):
    if not isinstance(used, (int, float)) or not isinstance(limit, (int, float)) or limit <= 0:
        return '—'
    return f'{max(0, min(100, 100 * (1-used/limit))):.0f}%'


def model_label(model):
    if not isinstance(model, str) or not model.strip():
        return 'Model unknown'
    name = model.rsplit('/', 1)[-1]
    if name.startswith('gpt-'):
        parts = name.split('-')
        return 'GPT-'+parts[1]+' '+ ' '.join(p.capitalize() for p in parts[2:])
    if name.startswith('claude-'):
        return name.replace('claude-', 'Claude ', 1).replace('-', ' ')
    return name.replace('_', ' ')


def model_lines(draw, label, font_path):
    # Fit model names in up to two lines, preserving full model identifiers.
    words = label.replace('-', '- ').split()
    for size in range(22, 11, -1):
        font = ImageFont.truetype(font_path, size)
        lines = ['']
        for word in words:
            candidate = (lines[-1]+' '+word).strip().replace('- ', '-')
            if draw.textlength(candidate, font=font) <= 124:
                lines[-1] = candidate
            else:
                lines.append(word)
        lines = [line for line in lines if line]
        if len(lines) <= 2 and all(draw.textlength(line, font=font) <= 124 for line in lines):
            return lines, font, size
    font = ImageFont.truetype(font_path, 14)
    remaining = label
    lines = []
    for _ in range(2):
        line = ''
        while remaining and draw.textlength(line+remaining[0]+'…', font=font) <= 124:
            line += remaining[0]
            remaining = remaining[1:]
        lines.append(line.strip())
        remaining = remaining.lstrip()
        if not remaining:
            break
    if remaining:
        lines[-1] += '…'
    return lines, font, 14


def telemetry_color(value):
    title, number, detail, color = value
    if not title and number == 'WAITING':
        color = '#f26672'
    if title in ('CONTEXT LEFT', 'QUOTA LEFT') and number.endswith('%'):
        remaining = float(number[:-1])
        if remaining <= 10:
            color = '#f26672'
        elif remaining <= 20:
            color = '#ffd447'
    return color


def animation_phase(value, now):
    return int(now*8) % 16 if telemetry_color(value) == '#f26672' else None


@lru_cache(maxsize=256)
def render(value, phase=None):
    title, number, detail, _ = value
    color = telemetry_color(value)
    image = Image.new('RGB', (144, 144), '#10141b')
    draw = ImageDraw.Draw(image)
    border, width = color, 2
    if color == '#f26672' and phase is not None:
        pulse = (1-math.cos(2*math.pi*phase/16))/2
        border = tuple(round(a+(b-a)*pulse) for a,b in zip((112,38,50),(255,135,144)))
        width = 2+round(2*pulse)
    draw.rounded_rectangle((4, 4, 139, 139), radius=13, outline=border, width=width)
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    bold = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    draw.text((72, 24), title, font=ImageFont.truetype(bold, 11), fill='#b8c4d4', anchor='mm')
    size = 32
    while draw.textlength(number, font=ImageFont.truetype(bold, size)) > 124:
        size -= 1
    draw.text((72, 40 if not title else 72), number, font=ImageFont.truetype(bold, size), fill=color, anchor='mm')
    if not title:
        lines, model_font, model_size = model_lines(draw, detail.upper(), bold)
        top = 96 - (len(lines)-1)*(model_size+3)/2
        for index, line in enumerate(lines):
            draw.text((72, top+index*(model_size+3)), line, font=model_font, fill='#e6ebf2', anchor='mm')
    else:
        draw.line((24, 103, 120, 103), fill='#344151', width=1)
        draw.text((72, 119), detail, font=ImageFont.truetype(font, 9), fill='#8797aa', anchor='mm')
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()
