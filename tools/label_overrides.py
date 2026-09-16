"""Persistent user label overrides, shared by the plugin, generator and installer."""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT/'opendeck-labels.json'


def read(path=OVERRIDES):
    return json.loads(path.read_text()) if path.exists() else {'version': 1, 'labels': {}}


@contextmanager
def locked(path):
    with path.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def merge(updates, path=OVERRIDES):
    if not updates:
        return
    with locked(path):
        data = read(path)
        data['labels'].update(updates)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')
        temporary.replace(path)


def capture(profile, fallback=None):
    """Capture app edits relative to generation defaults, including explicit blank labels."""
    updates = {}
    for pos, key in enumerate(profile.get('keys', [])):
        if not key:
            continue
        settings = key.get('settings', {})
        if not settings.get('_label_id') and fallback and pos < len(fallback['keys']):
            fresh = fallback['keys'][pos]
            if fresh and fresh['action']['uuid'] == key['action']['uuid']:
                settings = fresh['settings']
        label_id = settings.get('_label_id')
        defaults = settings.get('_label_defaults')
        if not label_id or defaults is None:
            continue
        titles = [s.get('text', '') for s in key['states']]
        changed = {str(i): text for i, text in enumerate(titles) if i < len(defaults) and text != defaults[i]}
        if not changed:
            continue
        if settings.get('_label_mode') == 'shared':
            # A common edit changes one state; if edits conflict, preserve the visible one.
            distinct = set(changed.values())
            title = next(iter(distinct)) if len(distinct) == 1 else changed.get(str(key['current_state']), list(changed.values())[-1])
            updates[label_id] = {'shared': title}
        else:
            updates[label_id] = {'states': {str(i): title for i, title in enumerate(titles)}}
    return updates


def apply(profile, labels):
    for key in profile.get('keys', []):
        if not key:
            continue
        override = labels.get(key['settings'].get('_label_id'))
        if not override:
            continue
        for i, state in enumerate(key['states']):
            title = override.get('shared') if 'shared' in override else override.get('states', {}).get(str(i))
            if title is not None:
                state['text'] = title


class LabelSync:
    def __init__(self, send, path=OVERRIDES):
        self.send = send
        self.path = path
        self.contexts = {}
        self.initial = set()

    def appear(self, context, settings):
        self.contexts[context] = settings
        self.initial.add(context)
        override = read(self.path)['labels'].get(settings.get('_label_id'), {})
        if settings.get('_label_mode') == 'shared' and 'shared' in override:
            self.send({'event': 'setTitle', 'context': context, 'payload': {'title': override['shared']}})

    def disappear(self, context):
        self.contexts.pop(context, None)
        self.initial.discard(context)

    def changed(self, context, payload):
        if context in self.initial:
            self.initial.remove(context)
            return  # willAppear sends the old/current title; it is not a user edit.
        settings = self.contexts.get(context, payload.get('settings', {}))
        label_id = settings.get('_label_id')
        if not label_id or settings.get('_label_mode') != 'shared' or 'title' not in payload:
            return
        title = payload['title']
        old = read(self.path)['labels'].get(label_id, {})
        if old.get('shared') == title:
            return
        merge({label_id: {'shared': title}}, self.path)
        self.send({'event': 'setTitle', 'context': context, 'payload': {'title': title}})
