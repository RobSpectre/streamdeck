"""Local state for the two Stream Deck audio buttons; no mixer/OBS state polling."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_FILE = '.audio-control-state.json'


class AudioControls:
    def __init__(self, root=ROOT, runner=None):
        self.root = Path(root)
        self.path = self.root/STATE_FILE
        self.runner = runner or self.run
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'mode': 'desktop', 'muted': False}
        if self.state.get('mode') not in ('desktop', 'broadcast') or type(self.state.get('muted')) is not bool:
            raise ValueError('Invalid local audio button state')
        self.sync_mode()

    def sync_mode(self):
        # The scene-switching script owns this marker. A second mode toggle in
        # JSON can start out opposite and then remain opposite on every press.
        mode = 'desktop' if (self.root/'mixer_in_desktop.txt').is_file() else 'broadcast'
        if mode != self.state['mode']:
            self.state.update(mode=mode, muted=False)

    def run(self, script):
        subprocess.run([str(self.root/script)], cwd=self.root, check=True, timeout=30)

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2)+'\n')
        temporary.replace(self.path)

    def indicator(self):
        self.sync_mode()
        if self.state['mode'] == 'desktop':
            return 0
        return 2 if self.state['muted'] else 1

    def activate(self, control):
        self.sync_mode()
        updated = self.state.copy()
        if control == 'audio_mode':
            self.runner('toggle_audio.sh')
            updated['mode'] = 'desktop' if (self.root/'mixer_in_desktop.txt').is_file() else 'broadcast'
            if updated['mode'] == 'broadcast':
                updated['muted'] = False
        elif control == 'mic_mute':
            self.runner('mute_mics.sh')
            updated['muted'] = not self.state['muted']
        else:
            raise ValueError('Unknown audio control')
        self.state = updated
        self.save()
