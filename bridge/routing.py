# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Read-only ownership evidence. Never connects, resumes, starts, or interrupts a thread."""
from datetime import datetime
import contextlib
import json
from pathlib import Path
from paths import CODEX_HOME
import re
import sqlite3
import subprocess
import uuid


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=5)
    if result.returncode not in (0, 1) or (result.returncode and result.stderr.strip()):
        raise RuntimeError('local inspection failed')
    return result.stdout


def open_pids(path):
    text = command(['/usr/sbin/lsof', '-nP', '-F', 'p', str(path)])
    return sorted({int(line[1:]) for line in text.splitlines() if re.fullmatch(r'p\d+', line)})


def history(path, target):
    meta = None
    last = None
    scanned = 0
    # Streaming, bounded inspection; do not return research prompts or tool output.
    with path.open() as stream:
        for line in stream:
            scanned += len(line)
            if scanned > 64*1024*1024:
                raise RuntimeError('history scan limit')
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get('payload', {})
            if record.get('type') == 'session_meta' and meta is None:
                if payload.get('id') != target:
                    raise RuntimeError('history identity mismatch')
                meta = {k: payload.get(k) for k in ('originator', 'source', 'cli_version')}
            if record.get('type') == 'event_msg' and payload.get('type') in ('task_started', 'task_complete', 'turn_aborted'):
                last = {'type': payload['type'], 'time': record.get('timestamp'), 'turn_id': payload.get('turn_id')}
    if meta is None:
        raise RuntimeError('history identity missing')
    return meta, last


def classify(owners, stable):
    if not stable:
        return '检查过程中记录或进程发生变化，状态不确定。'
    if not owners:
        return '未发现持有文件的进程；这不证明会话空闲或允许接管。'
    if len(owners) != 1:
        return '发现多个进程持有会话文件，归属不唯一，禁止发送。'
    owner = owners[0]
    if not owner['is_codex']:
        return '持有文件的进程不是已识别的 Codex 服务，禁止发送。'
    if not owner['tcp_listeners'] and not owner['named_unix_sockets']:
        return '原进程未发现 TCP 监听或命名 Unix 套接字，当前没有可验证的共享连接。'
    return '发现进程监听资源，但尚未验证为原会话的 App Server 接口，禁止发送。'


def inspect_thread(thread_id, home=None):
    """Only accepts an ID already authorized through the caller's actor-scoped refs."""
    uuid.UUID(thread_id)
    home = Path(home or CODEX_HOME).resolve()
    databases = sorted((p for p in home.glob('state_*.sqlite') if re.search(r'_(\d+)\.sqlite$', p.name)),
                       key=lambda p: int(re.search(r'_(\d+)\.sqlite$', p.name)[1]))
    if not databases:
        raise RuntimeError('state database missing')
    with contextlib.closing(sqlite3.connect(databases[-1].as_uri()+'?mode=ro', uri=True, timeout=3)) as db:
        row = db.execute('SELECT rollout_path,archived FROM threads WHERE id=?', (thread_id,)).fetchone()
    if not row:
        raise RuntimeError('thread missing')
    path = Path(row[0]).resolve()
    if not any(path.is_relative_to(home/prefix) for prefix in ('sessions', 'archived_sessions')):
        raise RuntimeError('history outside known store')
    before = path.stat()
    pids = open_pids(path)
    meta, last = history(path, thread_id)
    owners = []
    for pid in pids[:8]:
        fingerprint = command(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,lstart=,comm=']).strip()
        exe = command(['/bin/ps', '-p', str(pid), '-o', 'comm=']).strip()
        if not fingerprint or not exe:
            raise RuntimeError('holder exited during inspection')
        tcp = command(['/usr/sbin/lsof', '-nP', '-a', '-p', str(pid), '-iTCP', '-sTCP:LISTEN', '-F', 'n'])
        unix = command(['/usr/sbin/lsof', '-nP', '-a', '-p', str(pid), '-U', '-F', 'n'])
        owners.append({'pid': pid, 'exe': exe, 'is_codex': Path(exe).name == 'codex',
                       'fingerprint': fingerprint,
                       'tcp_listeners': sum(line.startswith('n') for line in tcp.splitlines()),
                       'named_unix_sockets': sum(line.startswith('n/') for line in unix.splitlines())})
    after = path.stat()
    stable = ((before.st_size,before.st_mtime_ns) == (after.st_size,after.st_mtime_ns)
              and pids == open_pids(path) and len(pids) <= 8)
    for owner in owners:
        stable &= owner['fingerprint'] == command(['/bin/ps','-p',str(owner['pid']),'-o','pid=,ppid=,lstart=,comm=']).strip()
    return {'thread_id': thread_id, 'archived': bool(row[1]), 'meta': meta, 'last': last,
            'owners': owners, 'stable': bool(stable), 'route_ready': False,
            'reason': '会话已归档，禁止自动接管。' if row[1] else classify(owners, stable),
            'checked_at': datetime.now().astimezone().isoformat(timespec='seconds')}


def render(report, label):
    meta, last = report['meta'], report['last']
    origin = str(meta.get('originator') or meta.get('source') or '未知')[:80]
    lines = [label, '原始 ID：'+report['thread_id'], '来源：'+origin]
    for owner in report['owners']:
        lines.append(f"文件持有进程：PID {owner['pid']} / {Path(owner['exe']).name}")
    if last:
        state = {'task_started':'记录为已开始（实时状态未确认）',
                 'task_complete':'最后记录已完成（不等于原进程实时空闲）',
                 'turn_aborted':'最后记录已中断'}[last['type']]
        lines.append(state+'\n记录时间：'+str(last['time']))
    else:
        lines.append('没有可核实的开始/结束记录。')
    lines += ['发送状态：阻止发送', report['reason'],
              '文件持有不是独占运行权证明；未向原服务查询到实时状态。',
              '未新建、恢复、迁移或发送任何会话。', '检查时间：'+report['checked_at']]
    return '\n'.join(lines)
