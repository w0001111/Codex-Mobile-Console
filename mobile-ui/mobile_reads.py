# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Bounded, read-only mobile history work and lightweight desktop observation."""
import threading
import time
from desktop_ipc import DesktopIPC, IPCError


class StatusIPC(DesktopIPC):
    # Following already publishes an initial snapshot in the installed desktop.
    # Do not force complete-history hydration just to inspect current status.
    def request(self, *args, **kwargs):
        self.read_deadline = time.monotonic() + self.timeout
        return super().request(*args, **kwargs)

    def _read(self, size):
        data = bytearray()
        while len(data) < size:
            remaining = self.read_deadline - time.monotonic()
            if remaining <= 0:
                raise IPCError('read-timeout')
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise IPCError('connection-closed')
            data.extend(chunk)
        return bytes(data)

    def snapshot(self, tid, owner):
        self.followed.add((tid, owner))
        self.snapshots.pop((tid, owner), None)
        self.read_deadline = time.monotonic() + self.timeout
        self._send(dict(type='broadcast', method='thread-stream-following-changed', version=1,
                        sourceClientId=self.client_id, targetClientIds=[owner],
                        params={'conversationId':tid, 'hostId':'local', 'following':True}))
        while (tid, owner) not in self.snapshots:
            if time.monotonic() >= self.read_deadline:
                raise IPCError('snapshot-timeout')
            self._receive()
        state = self.snapshots[(tid, owner)]['conversationState']
        if state.get('id') != tid or state.get('hostId') != 'local':
            raise IPCError('snapshot-identity-mismatch')
        return state


class ConnectIPC(StatusIPC):
    # Only used for an explicit web connection to an already validated saved ID.
    VERSIONS={k:v for k,v in StatusIPC.VERSIONS.items() if k not in ('thread-follower-start-turn','thread-follower-load-complete-history')}
    def connect_thread(self, tid, open_if_needed=False):
        import subprocess
        import uuid
        uuid.UUID(tid)
        if not open_if_needed:
            owner=self.owner(tid)
            return owner,self.snapshot(tid,owner)
        subprocess.run(['/usr/bin/open','-g','codex://threads/'+tid],check=True,capture_output=True,timeout=5)
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            self.timeout=min(1.5,max(.01,deadline-time.monotonic()))
            try:
                owner=self.owner(tid)
                self.timeout=min(3,max(.01,deadline-time.monotonic()))
                return owner,self.snapshot(tid,owner)
            except (IPCError,OSError):
                time.sleep(.15)
        raise IPCError('connection-timeout')


class ReadJobs:
    """Poll slow reads without occupying HTTP workers or starting duplicate work.

    Keys must include the authenticated actor and resolved thread, never a browser
    supplied job id. Keep only normalized public responses in this short cache.
    """
    def __init__(self, capacity=4, max_entries=128):
        self.lock = threading.Lock()
        self.jobs = {}
        self.capacity, self.max_entries = capacity, max_entries

    def poll(self, key, read, ttl=6):
        now = time.monotonic()
        with self.lock:
            expired = [k for k,v in self.jobs.items() if v['done'] and now-v['at'] > v['ttl']]
            for k in expired:
                del self.jobs[k]
            if key in self.jobs:
                job = self.jobs[key]
                return job['result'] if job['done'] else {'loading':True}
            if sum(not v['done'] for v in self.jobs.values()) >= self.capacity:
                return {'loading':True, 'queued':True}
            if len(self.jobs) >= self.max_entries:
                oldest = min((k for k,v in self.jobs.items() if v['done']), key=lambda k:self.jobs[k]['at'])
                del self.jobs[oldest]
            job = {'done':False, 'at':now, 'ttl':ttl}
            self.jobs[key] = job

        def run():
            try:
                result = read()
                result_ttl = ttl
            except Exception:
                result = {'error':'读取暂时失败，请重试；也可在电脑端检查该会话是否能打开。'}
                result_ttl = min(ttl, 6)
            with self.lock:
                job.update(done=True, result=result, at=time.monotonic(), ttl=result_ttl)
        threading.Thread(target=run, daemon=True).start()
        return {'loading':True}
