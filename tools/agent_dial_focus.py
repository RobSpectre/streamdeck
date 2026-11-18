#!/usr/bin/python3
"""Read focused desktop metadata; no focus changes or conversation capture."""
import json
import html
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dial_desktop import focused
from tools.suno_media import dbus_call, unique


def documents(node, api, depth=0):
    # Collection queries do not cross Electron's native/web accessibility boundary.
    if node.get_role() == api.Role.DOCUMENT_WEB:
        yield node
    elif depth < 10:
        for i in range(node.get_child_count()):
            child = node.get_child_at_index(i)
            if child:
                yield from documents(child, api, depth+1)


def select_screen(title, metas, visible_text=None):
    candidates = [m for m in metas if m.get('name') == title]
    if len(candidates) > 1 and visible_text is not None:
        # GNOME's native search result includes an escaped visible-screen snippet.
        # Compare as opaque text only; never retain, log or execute terminal text.
        normalized = ' '.join(visible_text.split())
        candidates = [m for m in candidates if len(snippet := ' '.join(
            html.unescape(m.get('description', '')).split())) >= 32 and snippet in normalized]
    return unique([m['id'] for m in candidates], 'focused terminal tab')


_CODEX_DOCUMENTS = {}


class CodexAccessibilityUnavailable(RuntimeError):
    """The focused app is known, but its task document is not accessible."""


def codex_title(window, api):
    """Cache native object handles, never focus state or the current task title."""
    for attempt in range(2):
        handles = _CODEX_DOCUMENTS.get(window)
        if handles is None:
            handles = []
            desktop = api.get_desktop(0)
            for i in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(i)
                if not app or app.get_name() != 'Codex':
                    continue
                app.set_cache_mask(api.Cache.NONE)
                for index in range(app.get_child_count()):
                    frame = app.get_child_at_index(index)
                    if frame and frame.get_state_set().contains(api.StateType.ACTIVE):
                        handles.extend((frame, doc) for doc in documents(frame, api))
            _CODEX_DOCUMENTS.clear()
            _CODEX_DOCUMENTS[window] = handles
        try:
            titles = []
            for frame, doc in handles:
                frame.clear_cache()
                doc.clear_cache()
                if not frame.get_state_set().contains(api.StateType.ACTIVE):
                    continue
                attrs = doc.get_document_iface().get_document_attributes()
                if attrs.get('URI') == 'app://-/index.html':
                    titles.append(attrs.get('Title'))
            return unique(titles, 'focused Codex task title')
        except Exception:
            _CODEX_DOCUMENTS.pop(window, None)
            if attempt:
                raise


def snapshot():
    window, fields = focused()
    classes = fields.get('WM_CLASS', [])
    result = {'window': window, 'agent': None}
    if 'Chatgpt' in classes and any('/.config/Codex)' in c for c in classes):
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        Atspi.set_timeout(500, 1000)
        try:
            title = codex_title(window, Atspi)
        except RuntimeError as error:
            raise CodexAccessibilityUnavailable('Codex task document unavailable') from error
        result.update(agent='codex', title=title)
    elif 'Gnome-terminal' in classes:
        from tools.dial_desktop import command
        title = command('xdotool', 'getwindowname', window)
        bus = unique(fields.get('_GTK_UNIQUE_BUS_NAME', []), 'terminal bus')
        path = '/org/gnome/Terminal/SearchProvider'
        iface = 'org.gnome.Shell.SearchProvider2'
        ids = dbus_call(bus, path, iface, 'GetInitialResultSet', '(as)', ([],))[0]
        metas = dbus_call(bus, path, iface, 'GetResultMetas', '(as)', (ids,))[0]
        text = None
        if len([m for m in metas if m.get('name') == title]) > 1:
            from tools.claude_dial import terminal_text
            text = terminal_text()
        screen = select_screen(title, metas, text)
        result.update(agent='terminal', screen=screen, bus=bus)
    if focused() != (window, fields):
        raise RuntimeError('Focus changed')
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(snapshot()))
    except Exception:
        print(json.dumps({'agent': None}))
