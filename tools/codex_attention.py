"""Read Codex desktop state and dispatch explicitly selected approval actions.

This uses the desktop's internal versioned IPC protocol, not a public API.
Only pending requests and runtime flags are retained from conversation snapshots.
"""
import copy
import json
from pathlib import Path
import socket
import struct
import threading
import time
import uuid

REQUESTS = {'item/commandExecution/requestApproval', 'item/fileChange/requestApproval',
            'item/permissions/requestApproval', 'item/tool/requestUserInput',
            'item/tool/requestOptionPicker', 'mcpServer/elicitation/request',
            'item/plan/requestImplementation'}
FIELDS = {'requests', 'threadRuntimeStatus', 'latestTokenUsageInfo', 'updatedAt', 'id', 'latestModel'}


def needs_input(state):
    flags = (state.get('threadRuntimeStatus') or {}).get('activeFlags', [])
    return bool(set(flags) & {'waitingOnApproval', 'waitingOnUserInput'}) or any(
        request.get('method') in REQUESTS for request in state.get('requests', []))


def apply_change(state, change):
    if change['type'] == 'snapshot':
        return {k: copy.deepcopy(v) for k, v in change['conversationState'].items() if k in FIELDS}
    state = copy.deepcopy(state)
    for patch in change.get('patches', []):
        path = patch['path']
        if not path or path[0] not in FIELDS:
            continue
        target = state
        for key in path[:-1]:
            target = target[key]
        key = path[-1]
        if patch['op'] == 'remove':
            del target[key]
        elif isinstance(target, list) and patch['op'] == 'add':
            target.insert(key, copy.deepcopy(patch['value']))
        else:
            target[key] = copy.deepcopy(patch['value'])
    return state


class CodexAttention:
    write_lock = threading.Lock()

    def __init__(self, presence=None):
        self.presence = presence
        self.lock = threading.Lock()
        self.states = {}
        self.connected = False
        self.sock = None
        self.owners = {}
        self.auto_thread = None
        self.sent_approvals = set()
        self.approval_messages = {}
        threading.Thread(target=self.run, daemon=True).start()

    def indicator(self):
        with self.lock:
            return int(self.connected and any(needs_input(s) for s in self.states.values()))

    def snapshot(self):
        with self.lock:
            return self.connected, copy.deepcopy(self.states)

    def actionable(self):
        return [(thread, request) for thread, state in self.snapshot()[1].items()
                for request in state.get('requests', []) if request.get('method') in
                ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval')]

    def approve_request(self, thread, request, scoped=False):
        key = (thread, str(request['id']))
        if key in self.sent_approvals or not self.sock or thread not in self.owners:
            return
        method = 'thread-follower-command-approval-decision' if request['method'] == 'item/commandExecution/requestApproval' else 'thread-follower-file-approval-decision'
        message_id = str(uuid.uuid4())
        self.send(self.sock, {'type': 'request', 'requestId': message_id,
                             'targetClientId': self.owners[thread], 'method': method, 'version': 1,
                             'params': {'conversationId': thread, 'requestId': request['id'],
                                        'decision': 'acceptForSession' if scoped else 'accept'}})
        self.sent_approvals.add(key)
        self.approval_messages[message_id] = key

    def extended_action(self, decision):
        requests = self.actionable()
        if len(requests) != 1:
            return
        thread, request = requests[0]
        if decision == 'auto':
            self.auto_thread = thread
        self.approve_request(thread, request, scoped=decision == 'allow_tool')

    @staticmethod
    def send(sock, message):
        data = json.dumps(message).encode()
        with CodexAttention.write_lock:
            sock.sendall(struct.pack('<I', len(data)) + data)

    @staticmethod
    def receive(sock):
        def exact(size):
            chunks = bytearray()
            while len(chunks) < size:
                data = sock.recv(size - len(chunks))
                if not data:
                    raise ConnectionError('Codex disconnected')
                chunks.extend(data)
            return chunks
        size = struct.unpack('<I', exact(4))[0]
        if not 0 < size <= 268435456:
            raise ValueError('Invalid IPC frame size')
        return json.loads(exact(size))

    def run(self):
        while True:
            if self.presence and not self.presence.wait('codex', visible=False):
                return
            try:
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.connect(str(Path.home()/'.codex/ipc/ipc.sock'))
                    self.send(sock, {'type': 'request', 'requestId': str(uuid.uuid4()),
                                    'method': 'initialize', 'params': {'clientType': 'opendeck-status'}})
                    owners = {}
                    self.sock, self.owners = sock, owners
                    revisions = {}
                    while True:
                        message = self.receive(sock)
                        if message.get('requestId') in self.approval_messages and message.get('type') == 'response':
                            key = self.approval_messages.pop(message['requestId'])
                            if message.get('resultType') == 'error':
                                self.auto_thread = None
                                self.sent_approvals.discard(key)
                        if message['type'] == 'client-discovery-request':
                            self.send(sock, {'type': 'client-discovery-response',
                                            'requestId': message['requestId'], 'response': {'canHandle': False}})
                            continue
                        method = message.get('method')
                        params = message.get('params', {})
                        if method == 'initialize':
                            with self.lock:
                                self.connected = True
                        elif method == 'thread-stream-following-changed' and params.get('hostId') == 'local':
                            thread = params['conversationId']
                            if params['following']:
                                owners[thread] = message['sourceClientId']
                                self.send(sock, {'type': 'broadcast', 'method': method, 'version': 1,
                                                'targetClientIds': [message['sourceClientId']], 'params': params})
                            else:
                                owners.pop(thread, None)
                                if self.auto_thread == thread:
                                    self.auto_thread = None
                                revisions.pop(thread, None)
                                with self.lock:
                                    self.states.pop(thread, None)
                                self.send(sock, {'type': 'broadcast', 'method': method, 'version': 1,
                                                'targetClientIds': [message['sourceClientId']], 'params': params})
                        elif method == 'thread-stream-state-changed' and params.get('hostId') == 'local':
                            if message.get('version') != 11:
                                raise ValueError('Codex state protocol changed')
                            thread, change = params['conversationId'], params['change']
                            if change['type'] == 'patches' and change['baseRevision'] != revisions.get(thread):
                                raise ValueError('Missed Codex state update; reconnecting')
                            with self.lock:
                                self.states[thread] = apply_change(self.states.get(thread, {}), change)
                            revisions[thread] = change['revision']
                            if self.auto_thread == thread:
                                for target, request in self.actionable():
                                    if target == thread:
                                        self.approve_request(target, request)
                        elif method == 'client-status-changed' and params['status'] == 'disconnected':
                            for thread, owner in list(owners.items()):
                                if owner == params['clientId']:
                                    owners.pop(thread)
                                    revisions.pop(thread, None)
                                    with self.lock:
                                        self.states.pop(thread, None)
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                with self.lock:
                    self.connected = False
                    self.states.clear()
                    self.sock = None
                    self.auto_thread = None
                    self.sent_approvals.clear()
                    self.approval_messages.clear()
                time.sleep(2)
