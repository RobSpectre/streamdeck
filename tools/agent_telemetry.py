"""Read locally recorded Claude Code and Hermes usage without changing agents."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
import time

from tools.codex_telemetry import compact, MONTH, context_left, model_label
from tools.cli_agent_bridge import sessions, pending


def hermes_cli_open(proc_root=Path('/proc')):
    """Detect the local interactive launcher, excluding gateways and helpers."""
    launcher = str(Path.home()/'.hermes/hermes-agent/hermes')
    for process in proc_root.glob('[0-9]*'):
        try:
            args = process.joinpath('cmdline').read_bytes().decode().split('\0')
            stat = process.joinpath('stat').read_text().rsplit(')', 1)[1].split()
            if launcher in args[:2] and int(stat[4]) != 0:
                return True
        except (OSError, ValueError, IndexError, UnicodeError):
            continue
    return False


def claude_tokens(usage):
    # Claude's input_tokens excludes cache creation and reads.
    return sum(usage.get(k, 0) or 0 for k in (
        'input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))


def hermes_usage(db, cutoff, session_id):
    # CanonicalUsage.total_tokens = uncached input + cache read/write + output.
    # Reasoning is already included in output. The ledger also includes auxiliary
    # calls which are deliberately absent from the sessions summary.
    buckets = '+'.join('COALESCE('+k+',0)' for k in
                       ('input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens'))
    cte = f'''WITH usage AS (
        SELECT session_id, {buckets} AS tokens, first_seen, last_seen
          FROM session_model_usage
        UNION ALL
        SELECT id, {buckets}, started_at, COALESCE(last_activity_at, started_at)
          FROM sessions s WHERE parent_session_id IS NULL AND NOT EXISTS (
            SELECT 1 FROM session_model_usage u WHERE u.session_id=s.id AND u.task='')
    ) '''
    month, overlaps, session = db.execute(cte+'''
        SELECT COALESCE(SUM(CASE WHEN first_seen>=? THEN tokens ELSE 0 END),0),
               COALESCE(SUM(CASE WHEN first_seen<? AND last_seen>=? AND tokens>0 THEN 1 ELSE 0 END),0),
               SUM(CASE WHEN session_id=? THEN tokens ELSE NULL END) FROM usage
    ''', (cutoff, cutoff, cutoff, session_id)).fetchone()
    return month, bool(overlaps), session


class AgentTelemetry:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {'claude': {}, 'hermes': {}}
        self.files = {}
        self.speed_samples = {}
        threading.Thread(target=self.scan, daemon=True).start()

    def claude(self, now):
        for path in (Path.home()/'.claude/projects').glob('**/*.jsonl'):
            record = self.files.setdefault(path, {'offset': 0, 'messages': {}, 'session': None, 'latest': 0})
            if path.stat().st_size < record['offset']:
                record.update(offset=0, messages={}, latest=0)
            with path.open('rb') as stream:
                stream.seek(record['offset'])
                while True:
                    line = stream.readline()
                    if not line or not line.endswith(b'\n'):
                        break
                    record['offset'] = stream.tell()
                    try:
                        item = json.loads(line)
                        stamp = datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00')).timestamp()
                        record['latest'] = max(record['latest'], stamp)
                        record['session'] = item.get('sessionId') or record['session']
                        message = item.get('message', {})
                        if item.get('type') != 'assistant' or not message.get('usage'):
                            continue
                        if message.get('model'):
                            record['model'] = message['model']
                        key = message.get('id') or item.get('requestId') or item['uuid']
                        value = claude_tokens(message['usage'])
                        previous = record['messages'].get(key)
                        # Streaming chunks repeat usage; retain the largest counter once.
                        if previous is None or value >= previous[1]:
                            record['messages'][key] = (stamp, value, message['usage'].get('output_tokens', 0))
                    except (ValueError, KeyError, TypeError):
                        continue
        messages = {}
        session = max(self.files.values(), key=lambda r: r['latest'], default={}).get('session')
        live = sessions('claude')
        if live:
            session = max(live, key=lambda v: (v.get('active', False), v['updated']))['session']
        session_messages = {}
        for record in self.files.values():
            for key, value in record['messages'].items():
                if key not in messages or value[1] > messages[key][1]:
                    messages[key] = value
                if record['session'] == session:
                    session_messages[key] = value
        model = max((r for r in self.files.values() if r['session'] == session), key=lambda r:r['latest'], default={}).get('model')
        return {'model': model, 'session': sum(v for _, v, _ in session_messages.values()) if session else None,
                'output': sum(o for _, _, o in session_messages.values()), 'session_id': session,
                'month': sum(v for t, v, _ in messages.values() if t >= now-MONTH) if messages else None}

    def hermes(self, now):
        path = Path.home()/'.hermes/state.db'
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
            latest = db.execute('SELECT input_tokens+output_tokens, output_tokens, id, model FROM sessions '
                                'WHERE parent_session_id IS NULL AND message_count>0 '
                                'ORDER BY COALESCE(last_activity_at,started_at) DESC LIMIT 1').fetchone()
            live = sessions('hermes')
            if live:
                session = max(live, key=lambda v: (v.get('active', False), v['updated']))['session']
                latest = db.execute('SELECT input_tokens+output_tokens, output_tokens, id, model FROM sessions WHERE id=?', (session,)).fetchone() or latest
            monthly, overlaps, session_total = hermes_usage(db, now-MONTH, latest[2] if latest else None)
        return {'model': latest[3] if latest else None, 'session': session_total, 'output': latest[1] if latest else None,
                'session_id': latest[2] if latest else None, 'month': monthly, 'month_lower_bound': bool(overlaps)}

    def scan(self):
        while True:
            for name in ['claude', 'hermes']:
                try:
                    value = getattr(self, name)(time.time())
                except (OSError, sqlite3.Error, ValueError):
                    value = {}
                with self.lock:
                    self.data[name] = value
            time.sleep(5)

    def values(self, name):
        with self.lock:
            data = self.data[name].copy()
        color = '#d97757' if name == 'claude' else '#0000f2'
        brand = 'CLAUDE' if name == 'claude' else 'HERMES'
        live = sessions(name)
        current = max(live, key=lambda v: (v.get('active', False), v['updated']), default={})
        waiting = any(p['agent'] == name for p in pending())
        active = any(v.get('active') for v in live)
        activity = 'WAITING' if waiting else 'ACTIVE' if active else 'IDLE' if live else 'OFFLINE'
        unlinked = name == 'hermes' and not live and hermes_cli_open()
        if unlinked and not waiting:
            activity = 'OPEN'
        speed = None
        if name == 'hermes':
            speed = current.get('native_tps')
        elif current.get('turn_started') and data.get('output') is not None and current['session'] == data.get('session_id'):
            key = (name, current['session'], current['turn_started'])
            sample = self.speed_samples.setdefault(key, (time.time(), data['output']))
            end = current.get('turn_ended') or time.time()
            if end > sample[0]:
                speed = max(0, data['output']-sample[1])/max(1, end-sample[0])
        quota, age = None, None
        rates = current.get('rate_limits', {})
        if name == 'claude' and time.time()-current.get('quota_updated', 0) < 180:
            windows = [(v, seconds) for k, seconds in [('five_hour', 18000), ('seven_day', 604800)]
                       if (v := rates.get(k)) and v.get('resets_at', 0) > time.time() and v.get('used_percentage') is not None]
            if windows:
                quota = max(0, min(100, 100-max(v['used_percentage'] for v, _ in windows)))
                window, duration = max(windows, key=lambda w:w[1])
                age = max(0, (time.time()-window['resets_at']+duration)/86400)
        remaining = current.get('context_remaining')
        context = f'{max(0, min(100, remaining)):.0f}%' if isinstance(remaining, (float, int)) else context_left(current.get('context_used'), current.get('context_limit'))
        month = compact(data.get('month'))
        if data.get('month_lower_bound') and month != '—':
            month = '≥'+month
        speed_detail = brand+' · OBSERVED AVG'
        if name == 'hermes':
            speed_detail = ('RESTART HERMES' if current and 'native_tps' not in current else
                            'NO API SAMPLES' if current and speed is None else 'HERMES · API AVG')
        return {
            'activity': ('', activity, model_label(current.get('model') or data.get('model')), color),
            'speed': ('TOKENS / SEC', (f'{speed:.0f}' if name == 'hermes' else f'{speed:.1f}') if speed is not None else '—', speed_detail, color),
            'session': ('SESSION TOKENS', compact(data.get('session')), brand+' · LATEST LOCAL', color),
            'month': ('30-DAY TOKENS', month, brand+' · LOCAL', color),
            'quota': ('QUOTA LEFT', f'{quota:.0f}%' if quota is not None else 'N/A', brand+' · ALLOWANCE', color),
            'context': ('CONTEXT LEFT', context, brand+' · LAST REQUEST', color),
        }
