#!/usr/bin/env python3
"""The Formula 1 page's keys: the commands those keys run.

Every key on the Formula 1 pages used to be the app's own run-command control.
The app refuses to let a plugin touch a key it does not own, so while they stayed
the app's, nothing on the page could carry the race director's status. They are
this plugin's controls now, each carrying the command it always ran, and this
module runs that command in the plugin's place.

The commands are the same text the app ran, run the same way: from the
repository, with the repository's virtual environment in front of PATH, because
the scripts and their state.json are named relative to it. That is the wrapper
the app's run-command action built for these keys, and doing it here instead
means a key no longer depends on the directory the app happened to be started
from.

A press does not wait for its command. A key that blocked the poll loop would
stall every other control on the deck, and these commands - starting a player,
seeking in a feed, fullscreening an onboard - take as long as they take.
"""
import argparse
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# What a driver key does, on either deck: the XL's driver selectors and the
# battle keys both make this call, so a driver behaves the same way either way.
DRIVER = 'python control_driver_feeds.py driver --driver_abbreviation {tla}'


class F1KeyError(RuntimeError):
    """A Formula 1 key could not run what it was asked to."""


def script(command):
    """The shell one key's command runs as, in the repository and its venv."""
    return 'cd {} || exit\nexport PATH={}:"$PATH"\n( {}\n)'.format(
        shlex.quote(str(ROOT)), shlex.quote(str(ROOT/'.venv/bin')), command)


def run(command):
    """Run one key's command from the repository, without waiting for it."""
    if not command or not command.strip():
        raise F1KeyError('No command on this key')
    try:
        return subprocess.Popen(script(command), shell=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as error:
        raise F1KeyError(f'{command}: {error}') from error


def driver(tla):
    """Show a driver the way the XL's driver selectors do, fullscreen or not."""
    if not tla:
        raise F1KeyError('No driver on this key')
    return run(DRIVER.format(tla=tla))


def onboard(tla):
    """Ensure a qualifying driver's onboard is fullscreen, without toggle-off."""
    if not tla or not tla.isascii() or not tla.isalpha() or len(tla) != 3:
        raise F1KeyError('Invalid driver acronym')
    return run(f'python -m tools.f1_battles --show-onboard {shlex.quote(tla.upper())}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--command', help='show a key command as it would be run')
    parser.add_argument('--driver', metavar='TLA', help='show a driver call as it would be run')
    arguments = parser.parse_args()
    if arguments.command:
        print(script(arguments.command))
    if arguments.driver:
        print(script(DRIVER.format(tla=arguments.driver)))


if __name__ == '__main__':
    main()
