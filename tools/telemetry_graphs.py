"""Bounded, local observations for hardware telemetry graphs (no backfill)."""
import hashlib
import math
from pathlib import Path
import sqlite3

WINDOWS = {'speed': (600, 5), 'context': (600, 5), 'session': (600, 5),
           'month': (86400, 600)}


class GraphHistory:
    def __init__(self, path=None):
        path = Path(path) if path else Path.home()/'.cache/opendeck-agents/telemetry-graphs.sqlite'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS samples ('
                        'agent TEXT, metric TEXT, bucket INTEGER, value REAL, scope TEXT, '
                        'PRIMARY KEY(agent, metric, bucket))')
        if self.db.execute('PRAGMA user_version').fetchone()[0] < 1:
            # Old TPS rows repeated retained averages while idle. Their activity
            # was not stored, so discard only that series instead of guessing.
            with self.db:
                self.db.execute("DELETE FROM samples WHERE metric='speed'")
                self.db.execute('PRAGMA user_version=1')
        self.last = {}

    def observe(self, agent, samples, now):
        if agent not in ('codex', 'claude', 'hermes'):
            raise ValueError('Unknown agent')
        with self.db:
            for metric, (window, step) in WINDOWS.items():
                bucket = int(now // step)
                value, scope = samples.get(metric, (None, None))
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                    value = None
                if metric == 'context' and value is not None:
                    value = max(0, min(100, value))
                previous = self.last.get((agent, metric))
                if previous is None:
                    row = self.db.execute('SELECT value FROM samples WHERE agent=? AND metric=? AND bucket=?',
                                          (agent, metric, bucket)).fetchone()
                    if row is not None:
                        previous = (bucket, row[0] is not None)
                if previous == (bucket, True) or (previous == (bucket, False) and value is None):
                    continue
                # Keep task boundaries without storing task names or raw session IDs.
                scope = hashlib.sha256(str(scope).encode()).hexdigest() if scope else ''
                self.db.execute('INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?)',
                                (agent, metric, bucket, value, scope))
                self.db.execute('DELETE FROM samples WHERE agent=? AND metric=? AND (bucket<=? OR bucket>?)',
                                (agent, metric, bucket-window//step, bucket))
                self.last[agent, metric] = (bucket, value is not None)

    def series(self, agent, metric, now):
        if metric not in WINDOWS:
            return ()
        window, step = WINDOWS[metric]
        end = int(now // step)
        count = window // step
        rows = dict((bucket, (value, scope)) for bucket, value, scope in self.db.execute(
            'SELECT bucket, value, scope FROM samples WHERE agent=? AND metric=? AND bucket>? AND bucket<=?',
            (agent, metric, end-count, end)))
        points = []
        previous_scope = None
        for bucket in range(end-count+1, end+1):
            value, scope = rows.get(bucket, (None, None))
            if value is not None and previous_scope is not None and scope != previous_scope and points:
                points[-1] = None  # Never connect two tasks with a fake drop/rise.
            points.append(value)
            previous_scope = scope if value is not None else None
        return tuple(points)

    def close(self):
        self.db.close()
