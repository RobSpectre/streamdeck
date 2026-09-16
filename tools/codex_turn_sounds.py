#!/usr/bin/env python3
"""Play sounds for new terminal turns recorded by the local Codex app.

Reads Codex's internal history schema; a future app update may require changes.
Run under the desktop user's systemd manager for access to PulseAudio/PipeWire.
"""
import logging
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import time

DATABASE = Path.home() / '.codex/thread_history_1.sqlite'
SOUND_DIR = Path('/media/rspectre/Storage/Video/Sound Effects')
SOUNDS = {'failed': SOUND_DIR / 'icq.wav',
          'completed': SOUND_DIR / 'mk64_item_drop.wav'}


def terminal_turns(connection):
    return {(thread, turn): status for thread, turn, status in connection.execute(
        "SELECT thread_id, turn_id, status FROM thread_turns "
        "WHERE status IN ('completed', 'failed', 'interrupted')")}


def play_status(status):
    sound = SOUNDS.get(status)
    if sound is not None:
        subprocess.run(['/usr/bin/paplay', str(sound)], check=True, timeout=30)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    seen = None
    while True:
        try:
            with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True,
                                         timeout=2)) as connection:
                current = terminal_turns(connection)
            if seen is None:
                seen = set(current)
                logging.info('Watching new Codex turn statuses; historical turns skipped')
            else:
                for key in current.keys() - seen:
                    seen.add(key)
                    status = current[key]
                    try:
                        play_status(status)
                        if status in SOUNDS:
                            logging.info('Played %s sound for turn %s', status, key[1])
                    except (OSError, subprocess.SubprocessError):
                        logging.exception('Unable to play %s sound', status)
        except sqlite3.Error:
            logging.exception('Unable to read Codex turn history')
        time.sleep(1)


if __name__ == '__main__':
    main()
