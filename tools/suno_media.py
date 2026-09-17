#!/usr/bin/python3
"""Prefer open Spotify over Suno; never send global media keys."""
import argparse
from urllib.parse import urlsplit
import time


def suno_url(value):
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and url.hostname in ('suno.com', 'www.suno.com')
    except ValueError:
        return False


def transport_name(name, action):
    return name in ({'Playbar: Play button', 'Playbar: Pause button'} if action == 'play'
                    else {'Playbar: Next Song button'} if action == 'next' else set())


def unique(items, description):
    if len(items) != 1:
        raise RuntimeError(f'Expected one {description}; found {len(items)}')
    return items[0]


def matches(node, role, api):
    rule = api.MatchRule.new(api.StateSet.new([]), api.CollectionMatchType.ALL,
                            {}, api.CollectionMatchType.ALL, [role], api.CollectionMatchType.ANY,
                            [], api.CollectionMatchType.ALL, False)
    return node.get_collection_iface().get_matches(rule, api.CollectionSortOrder.CANONICAL, 0, True)


def click(node):
    interface = node.get_action_iface()
    actions = [i for i in range(interface.get_n_actions())
               if interface.get_action_name(i) in ('doDefault', 'click', 'press')]
    index = unique(actions, 'default accessibility action')
    if not interface.do_action(index):
        raise RuntimeError('Browser rejected the accessibility action')


def dbus_call(destination, path, interface, method, signature=None, args=()):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return bus.call_sync(destination, path, interface, method,
                         GLib.Variant(signature, args) if signature else None, None,
                         Gio.DBusCallFlags.NO_AUTO_START, 2000, None).unpack()


def spotify_control(action, check=False):
    names = dbus_call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                      'org.freedesktop.DBus', 'ListNames')[0]
    players = [name for name in names if name == 'org.mpris.MediaPlayer2.spotify'
               or name.startswith('org.mpris.MediaPlayer2.spotify.')]
    if not players:
        return False
    player = unique(players, 'Spotify player')
    # Bind to this running process; never auto-launch or retarget after a race.
    owner = dbus_call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                      'org.freedesktop.DBus', 'GetNameOwner', '(s)', (player,))[0]
    interface = 'org.mpris.MediaPlayer2.Player'
    path = '/org/mpris/MediaPlayer2'
    properties = dbus_call(owner, path, 'org.freedesktop.DBus.Properties',
                           'GetAll', '(s)', (interface,))[0]
    method = {'play': 'PlayPause', 'next': 'Next'}[action]
    capability = ('CanGoNext' if action == 'next' else
                  'CanPause' if properties.get('PlaybackStatus') == 'Playing' else 'CanPlay')
    if not properties.get('CanControl') or not properties.get(capability):
        raise RuntimeError('Spotify is open but this control is unavailable; select a track first')
    if check:
        print(f'Verified Spotify {action} control; no playback action sent.')
    else:
        dbus_call(owner, path, interface, method)
    return True


def run(action, check=False):
    if not spotify_control(action, check):
        suno_control(action, check)


def suno_control(action, check=False):
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    Atspi.set_timeout(1000, 2000)
    desktop = Atspi.get_desktop(0)
    tabs = []
    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        if not app or app.get_name() not in ('Google Chrome', 'Chromium'):
            continue
        # Chrome's cached child array can contain None for populated windows.
        app.set_cache_mask(Atspi.Cache.NONE)
        for number in range(app.get_child_count()):
            window = app.get_child_at_index(number)
            if not window or not window.get_name():
                continue
            for tab in matches(window, Atspi.Role.PAGE_TAB, Atspi):
                if 'suno' in tab.get_name().lower():
                    tabs.append((window, tab))
    window, tab = unique(tabs, 'Suno browser tab')
    # Selecting the exact tab is allowed; no global keyboard/mouse input is used.
    if not tab.get_state_set().contains(Atspi.StateType.SELECTED):
        click(tab)
    deadline = time.monotonic()+2
    while True:
        documents = [doc for doc in matches(window, Atspi.Role.DOCUMENT_WEB, Atspi)
                     if suno_url(doc.get_document_iface().get_document_attributes().get('URI', ''))]
        if documents or time.monotonic() >= deadline:
            break
        time.sleep(.1)
    doc = unique(documents, 'verified suno.com document')
    buttons = [button for button in matches(doc, Atspi.Role.PUSH_BUTTON, Atspi)
               if transport_name(button.get_name(), action)]
    button = unique(buttons, 'Suno playbar control')
    # Recheck navigation and tab selection immediately before dispatch.
    if not tab.get_state_set().contains(Atspi.StateType.SELECTED) or not suno_url(
            doc.get_document_iface().get_document_attributes().get('URI', '')):
        raise RuntimeError('Suno tab changed before playback action')
    if check:
        print(f'Verified Suno {action} control; no playback action sent.')
    else:
        if not button.get_state_set().contains(Atspi.StateType.ENABLED):
            raise RuntimeError('Suno playback control is disabled; select a song first')
        click(button)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['play', 'next'])
    parser.add_argument('--check', action='store_true', help='Verify Spotify or locate/select Suno without changing playback')
    args = parser.parse_args()
    run(args.action, args.check)
