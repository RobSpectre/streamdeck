"""Optional machine-local installation paths; never shared runtime state."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def codex_executable():
    path = ROOT/'portable-machine.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    return str(Path(settings.get('codex_executable', '/usr/lib/chatgpt/resources/codex')).expanduser())
