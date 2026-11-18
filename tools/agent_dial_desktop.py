#!/usr/bin/python3
"""Small system-Python worker retaining the native accessibility connection."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.agent_dial_focus import snapshot
from tools.claude_dial import run

for line in sys.stdin:
    try:
        request = json.loads(line)
        if request['action'] == 'focus':
            value = snapshot()
        elif request['action'] == 'claude':
            value = run(request['operation'], request['target'], request.get('parameter', 'model'), request.get('ticks', 0))
        else:
            raise ValueError('Unknown desktop read/action')
        print(json.dumps({'result': value}), flush=True)
    except Exception as error:
        print(json.dumps({'error': type(error).__name__}), flush=True)
