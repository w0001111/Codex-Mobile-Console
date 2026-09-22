# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Read actual user/final timestamps without opening or hydrating desktop tasks.

Only time, event kind and file cursors are cached. Source paths come from the
desktop's read-only registry, and the rollout session identity must match.
"""
import contextlib
from datetime import datetime
import json
import os
import sqlite3
import threading
from pathlib import Path

MAX_LINE = 8 * 1024 * 1024


def event_time(line):
    if not any(word in line for word in (b'"user"', b'"user_message"', b'"final_answer"', b'"task_complete"')):
        return None
    try:
        event = json.loads(line)
        payload = event.get('payload') or {}
        kind = None
        if event.get('type') == 'response_item' and payload.get('type') == 'message':
            if payload.get('role') == 'user': kind = 'sent'
            elif payload.get('role') == 'assistant' and payload.get('phase') == 'final_answer': kind = 'reply'
        elif event.get('type') == 'event_msg':
            if payload.get('type') == 'user_message': kind = 'sent'
            elif payload.get('type') == 'task_complete' and payload.get('last_agent_message'): kind = 'reply'
        if not kind: return None
        stamp = event.get('timestamp')
        at = datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
        if at <= 0: return None
        return at, kind
    except (ValueError, TypeError, AttributeError):
        return None


def reverse_lines(handle, end, floor=0):
    """Read backwards with bounded memory, ignoring incomplete/oversized lines."""
    position, buffer, dropping = end, b'', False
    while position > floor:
        count = min(65536, position - floor)
        position -= count
        handle.seek(position)
        parts = (handle.read(count) + buffer).split(b'\n')
        if dropping:
            if len(parts) == 1:
                buffer = b''
                continue
            parts.pop()  # Tail of an oversized line discarded in a later block.
            dropping = False
        for line in reversed(parts[1:]):
            if len(line) <= MAX_LINE: yield line
        buffer = parts[0]
        if len(buffer) > MAX_LINE: buffer = b''; dropping = True
    if buffer and not dropping: yield buffer


class MessageActivity:
    def __init__(self, directory, registry=None):
        self.registry = registry
        self.directory = Path(directory)
        self.path = self.directory / 'message-activity.sqlite3'
        self.lock = threading.Lock()

    def _registry(self):
        if self.registry: return Path(self.registry)
        candidates = [p for p in Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))).expanduser().resolve().glob('state_*.sqlite') if p.stem.split('_')[-1].isdigit()]
        return max(candidates, key=lambda p: int(p.stem.split('_')[-1]))

    def listing(self, thread_ids):
        ids = set(thread_ids)
        if not ids: return {}
        try:
            with contextlib.closing(sqlite3.connect(self._registry().as_uri()+'?mode=ro', uri=True, timeout=2)) as registry:
                paths = [(tid, path) for tid, path in registry.execute('SELECT id,rollout_path FROM threads WHERE archived=0') if tid in ids]
        except (OSError, ValueError, sqlite3.Error):
            return {}
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with contextlib.closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                self.path.chmod(0o600)
                db.execute('CREATE TABLE IF NOT EXISTS activity (thread TEXT PRIMARY KEY, path TEXT, device INTEGER, inode INTEGER, size INTEGER, mtime INTEGER, at REAL, kind TEXT)')
                result = {}
                for tid, name in paths:
                    previous = db.execute('SELECT path,device,inode,size,mtime,at,kind FROM activity WHERE thread=?', (tid,)).fetchone()
                    try:
                        path = Path(name)
                        with path.open('rb') as handle:
                            info = os.fstat(handle.fileno())
                            signature = (str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                            if previous and tuple(previous[:5]) == signature:
                                at, kind = previous[5:]
                            else:
                                first = handle.readline(65536)
                                meta = json.loads(first)
                                if meta.get('type') != 'session_meta' or meta.get('payload', {}).get('id') != tid:
                                    continue
                                append = previous and tuple(previous[:3]) == signature[:3] and info.st_size > previous[3]
                                floor = previous[3] if append else 0
                                at, kind = previous[5:] if append else (0, '')
                                # Only index complete records so a partial append is
                                # reconsidered on the next refresh.
                                end = info.st_size
                                handle.seek(max(0, end-1))
                                if handle.read(1) != b'\n':
                                    handle.seek(max(0, end-MAX_LINE))
                                    tail = handle.read(MAX_LINE)
                                    last = tail.rfind(b'\n')
                                    end = max(0, info.st_size-MAX_LINE) + last + 1 if last >= 0 else floor
                                for line in reverse_lines(handle, end, floor):
                                    found = event_time(line)
                                    if found:
                                        if found[0] > at: at, kind = found
                                        break
                                signature = (*signature[:3], end, signature[4])
                                db.execute('INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?,?,?,?)', (tid, *signature, at, kind))
                            result[tid] = {'messageAt': at, 'messageKind': kind}
                    except (OSError, ValueError, TypeError, sqlite3.Error):
                        if previous:
                            result[tid] = {'messageAt': previous[5], 'messageKind': previous[6]}
                return result
