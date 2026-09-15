# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Client for the installed desktop's private, same-user follower IPC.

No app-server process is spawned. No ownership/settings/approval mutations.
Protocol observed in ChatGPT desktop app build on 2026-09-14; fail closed.
"""
import json
import os
from pathlib import Path
import socket
import stat
import struct
import time
import uuid
import subprocess
from paths import CODEX_HOME


class IPCError(RuntimeError):
    pass


class DesktopIPC:
    VERSIONS = {'initialize': 0, 'thread-owner-discovery': 1,
                'thread-follower-load-complete-history': 1,
                'thread-follower-start-turn': 2}

    def __init__(self, path=None, timeout=12):
        self.path = Path(path or CODEX_HOME/'ipc/ipc.sock')
        self.timeout = timeout
        self.sock = None
        self.client_id = ''
        self.snapshots = {}
        self.followed = set()

    def __enter__(self):
        p, s = self.path.parent.lstat(), self.path.lstat()
        if not stat.S_ISDIR(p.st_mode) or not stat.S_ISSOCK(s.st_mode):
            raise IPCError('invalid-socket')
        if p.st_uid != os.getuid() or s.st_uid != os.getuid() or (p.st_mode | s.st_mode) & 0o077:
            raise IPCError('unsafe-socket-permissions')
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))
        try:
            r = self.request('initialize', {'clientType': 'wechat-controller'})
            self.client_id = r['result']['clientId']
        except BaseException:
            self.sock.close()
            raise
        return self

    def __exit__(self, *args):
        if self.sock:
            self.sock.close()

    def _send(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.sock.sendall(struct.pack('<I', len(data))+data)

    def _read(self, size):
        data = bytearray()
        while len(data) < size:
            piece = self.sock.recv(size-len(data))
            if not piece:
                raise IPCError('connection-closed')
            data.extend(piece)
        return bytes(data)

    def _receive(self):
        size = struct.unpack('<I', self._read(4))[0]
        if not 0 < size <= 64*1024*1024:
            raise IPCError('frame-limit')
        msg = json.loads(self._read(size))
        if msg.get('type') == 'client-discovery-request':
            self._send({'type':'client-discovery-response', 'requestId':msg['requestId'],
                        'response': {'canHandle':False}})
        if msg.get('type') == 'broadcast' and msg.get('method') == 'thread-stream-state-changed':
            p = msg.get('params', {})
            change = p.get('change', {})
            key = (p.get('conversationId'), msg.get('sourceClientId'))
            if key in self.followed and p.get('hostId') == 'local' and change.get('type') == 'snapshot':
                self.snapshots[key] = change
        return msg

    def request(self, method, params, target=None):
        if method not in self.VERSIONS:
            raise IPCError('method-not-allowed')
        rid = str(uuid.uuid4())
        obj = dict(type='request', requestId=rid, sourceClientId=self.client_id,
                   version=self.VERSIONS[method], method=method, params=params,
                   timeoutMs=int(self.timeout*1000))
        if target:
            obj['targetClientId'] = target
        self._send(obj)
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(.01,deadline-time.monotonic()))
            r = self._receive()
            if r.get('type') == 'response' and r.get('requestId') == rid:
                if r.get('resultType') != 'success':
                    raise IPCError(r.get('error', 'unknown-error'))
                if target and r.get('handledByClientId') != target:
                    raise IPCError('owner-mismatch')
                return r
        raise IPCError('request-timeout')

    def owner(self, tid):
        uuid.UUID(tid)
        r = self.request('thread-owner-discovery', {'hostId':'local','conversationId':tid})
        return r['handledByClientId']

    def snapshot(self, tid, owner):
        self.followed.add((tid,owner))
        self.snapshots.pop((tid,owner),None)
        self._send(dict(type='broadcast',method='thread-stream-following-changed',version=1,
                        sourceClientId=self.client_id,targetClientIds=[owner],
                        params={'conversationId':tid,'hostId':'local','following':True}))
        self.request('thread-follower-load-complete-history', {'conversationId':tid}, owner)
        deadline = time.monotonic()+self.timeout
        while (tid,owner) not in self.snapshots:
            self.sock.settimeout(max(.01,deadline-time.monotonic()))
            if time.monotonic() >= deadline:
                raise IPCError('snapshot-timeout')
            self._receive()
        state = self.snapshots[(tid,owner)]['conversationState']
        if state.get('id') != tid or state.get('hostId') != 'local':
            raise IPCError('snapshot-identity-mismatch')
        return state

    def connect_thread(self, tid, open_if_needed=False):
        try:
            owner = self.owner(tid)
        except IPCError as e:
            if str(e) != 'no-client-found' or not open_if_needed:
                raise
            # Normal app deep link: desktop loads the SAME saved thread itself.
            # No CLI resume, private FD attachment, or ownership impersonation.
            uuid.UUID(tid)
            subprocess.run(['/usr/bin/open', '-g', 'codex://threads/'+tid],
                           check=True, capture_output=True, timeout=5)
            deadline = time.monotonic()+10
            while True:
                try:
                    owner = self.owner(tid)
                    break
                except IPCError as err:
                    if str(err) != 'no-client-found' or time.monotonic() >= deadline:
                        raise
                    time.sleep(.25)
        return owner, self.snapshot(tid, owner)

    def start(self, tid, owner, text, message_id):
        return self.request('thread-follower-start-turn', {
            'conversationId':tid,
            'turnStart':{'request':{'threadId':tid, 'input':[{'type':'text','text':text,'text_elements':[]}],
                                    'clientUserMessageId':message_id},
                         'context':{'inheritThreadSettings':True}}}, owner)


def turns(state):
    history = state.get('turnHistory') or {}
    if history.get('kind') == 'canonical':
        entities = history.get('history', {}).get('entitiesByKey', {})
        result = [v for v in entities.values() if isinstance(v,dict) and v.get('turnId')]
    else:
        result = state.get('turns') or []
    return sorted(result,key=lambda t:t.get('turnStartedAtMs') or 0)


def latest_result(state, turn_id=None):
    candidates = [t for t in turns(state) if turn_id is None or t.get('turnId') == turn_id]
    if not candidates:
        return None, ''
    t = candidates[-1]
    items = [x for x in t.get('items',[]) if x.get('type') == 'agentMessage' and x.get('text')]
    finals = [x for x in items if x.get('phase') == 'final_answer']
    return t, '\n\n'.join(x['text'] for x in (finals or items))


def ensure_idle(state):
    if state.get('threadRuntimeStatus',{}).get('type') != 'idle':
        raise IPCError('thread-not-idle')
    if state.get('requests') or state.get('threadGoalResumeConfirmation'):
        raise IPCError('thread-needs-user-input')
    if any(t.get('status') == 'inProgress' for t in turns(state)):
        raise IPCError('thread-not-idle')

if __name__ == '__main__':
    import sys
    with DesktopIPC() as client:
        tid=sys.argv[1]
        owner=client.owner(tid)
        state=client.snapshot(tid,owner)
        print(json.dumps({'thread_id':tid,'owner':owner,'keys':list(state),
                          'runtime':state.get('threadRuntimeStatus'),
                          'turns':len(state.get('turns',[])),
                          'permission_keys':list((state.get('currentPermissions') or {}).keys())},ensure_ascii=False))
