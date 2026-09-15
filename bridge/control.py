#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""WeChat read-only controller; authenticated identity arrives on JSON stdin."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from paths import ROOT, BRIDGE_STATE
from readonly_transport import Server

HELP = ('会话总控（只读）\n'
        '会话列表 [关键词]｜会话下一页\n'
        '会话查看 T0001｜会话选择 T0001\n'
        '会话路由 T0001（检查归属和发送条件）\n'
        '会话当前｜会话退出\n'
        '选择仅保存查看目标，不切换当前聊天；会话发送暂不开放。')


def clean(text, limit=1800):
    text = re.sub(r'(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+', '[已隐藏凭据]', str(text))
    return text if len(text) <= limit else text[:limit] + '\n…（内容已截断）'


class ReadOnlyAPI:
    """Hard method allowlist: no resume/start/steer/interrupt capability."""
    METHODS = {'thread/list', 'thread/read', 'thread/turns/list'}

    def __init__(self):
        self.server = None

    def request(self, method, params):
        if method not in self.METHODS:
            raise ValueError('Mutating API is disabled')
        if self.server is None:
            self.server = Server(ROOT)
            self.server.deadline = time.monotonic() + 40
            self.server.initialize()
        return self.server.request(method, params)

    def close(self):
        if self.server:
            self.server.close()


class Controller:
    def __init__(self, directory, api, inspector=None):
        self.api = api
        self.inspector = inspector
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        path = directory / 'control.sqlite3'
        # Create with restrictive permissions before SQLite opens the file.
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS refs (
              actor TEXT, number INTEGER, thread_id TEXT, title TEXT, cwd TEXT,
              PRIMARY KEY(actor, number), UNIQUE(actor, thread_id));
            CREATE TABLE IF NOT EXISTS choices (
              actor TEXT PRIMARY KEY, number INTEGER);
            CREATE TABLE IF NOT EXISTS pages (
              actor TEXT PRIMARY KEY, cursor TEXT, query TEXT);
            CREATE TABLE IF NOT EXISTS deliveries (
              actor TEXT, message_id TEXT, digest TEXT, response TEXT,
              created REAL, PRIMARY KEY(actor, message_id));
        ''')

    def close(self):
        self.db.close()

    def handle(self, envelope):
        required = ('project', 'platform', 'session_key', 'user_id', 'message_id')
        if envelope.get('version') != 1 or any(
                not isinstance(envelope.get(k), str) or not envelope[k] for k in required):
            return '缺少可信消息身份，未执行任何操作。'
        if envelope['platform'] != 'weixin':
            return '这一版会话总控仅开放给微信入口。'
        args = envelope.get('args') or []
        if not isinstance(args, list) or len(args) > 32 or any(
                not isinstance(x, str) or len(x) > 4000 for x in args):
            return '命令参数无效或过长。'
        actor = hashlib.sha256(json.dumps([envelope[k] for k in required[:-1]],
                                         ensure_ascii=False).encode()).hexdigest()
        digest = hashlib.sha256(json.dumps(args, ensure_ascii=False).encode()).hexdigest()
        # Route reports are observations: never reuse a stale cached process snapshot.
        if args and args[0] in ('route', '路由'):
            return self._dispatch(actor, args)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT digest,response FROM deliveries WHERE actor=? AND message_id=?',
                                  (actor, envelope['message_id'])).fetchone()
            if old:
                return old[1] if old[0] == digest else '同一消息编号对应不同内容，已拒绝执行。'
            response = self._dispatch(actor, args)
            self.db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?)',
                            (actor, envelope['message_id'], digest, response, time.time()))
            # Retain seven days of reply deduplication; this phase never starts tasks.
            self.db.execute('DELETE FROM deliveries WHERE created < ?', (time.time() - 7 * 86400,))
            return response

    def _dispatch(self, actor, args):
        action = args[0] if args else 'help'
        if action in ('help', '帮助'):
            return HELP
        if action in ('list', '列表'):
            return self._list(actor, ' '.join(args[1:]), None)
        if action in ('next', '下一页'):
            page = self.db.execute('SELECT cursor,query FROM pages WHERE actor=?', (actor,)).fetchone()
            if not page or not page[0]:
                return '没有下一页，请发送“会话列表”。'
            return self._list(actor, page[1], page[0])
        if action in ('leave', '退出'):
            self.db.execute('DELETE FROM choices WHERE actor=?', (actor,))
            return '已清除总控查看目标；当前聊天未切换。'
        if action in ('send', '发送'):
            return '未发送：既有会话尚未建立可验证的原服务连接。请发送“会话路由 T编号”检查具体原因。不会另起 resume，也不会启动任何模型任务。'
        if action in ('select', '选择', 'show', '查看', 'current', '当前', 'route', '路由'):
            token = args[1] if len(args) == 2 else None
            if action in ('current', '当前') or (action in ('show', '查看', 'route', '路由') and len(args) == 1):
                choice = self.db.execute('SELECT number FROM choices WHERE actor=?', (actor,)).fetchone()
                token = f'T{choice[0]:04d}' if choice else None
            if not token or not re.fullmatch(r'T\d{4,9}', token.upper()):
                return '请先发送“会话列表”，再使用稳定编号，例如“会话选择 T0001”。'
            number = int(token[1:])
            row = self.db.execute('SELECT thread_id,title,cwd FROM refs WHERE actor=? AND number=?',
                                  (actor, number)).fetchone()
            if not row:
                return '这个编号不属于你的会话目录，请先发送“会话列表”。'
            label = f'T{number:04d}｜{clean(row[1], 100)}'
            if action in ('route', '路由'):
                from routing import inspect_thread, render
                try:
                    return clean(render((self.inspector or inspect_thread)(row[0]), label), 3000)
                except Exception:
                    return label+'\n路由检查未完成，归属/运行状态未知，禁止发送。未创建或恢复会话。'
            if action in ('select', '选择'):
                self.db.execute('INSERT OR REPLACE INTO choices VALUES (?,?)', (actor, number))
                return f'已选择查看目标：{label}\n只读，未切换当前聊天，也未启动该会话。发送“会话查看”读取最近结果。'
            if action in ('current', '当前'):
                return f'当前总控查看目标：{label}\n运行状态未知；只读。'
            return self._show(row[0], label)
        return HELP

    def _list(self, actor, query, cursor):
        result = self.api.request('thread/list', {
            'limit': 10, 'cursor': cursor, 'sortKey': 'updated_at', 'sortDirection': 'desc',
            'modelProviders': [], 'sourceKinds': ['cli', 'vscode', 'exec', 'appServer', 'unknown'],
            'archived': False, 'searchTerm': query or None, 'useStateDbOnly': True})
        lines = ['跨项目会话目录（只读；运行状态未知）']
        for thread in result.get('data', []):
            title = ' '.join((thread.get('name') or thread.get('preview') or '未命名会话').split())[:100]
            row = self.db.execute('SELECT number FROM refs WHERE actor=? AND thread_id=?',
                                  (actor, thread['id'])).fetchone()
            if row:
                number = row[0]
            else:
                number = self.db.execute('SELECT COALESCE(MAX(number),0)+1 FROM refs WHERE actor=?',
                                         (actor,)).fetchone()[0]
            self.db.execute('INSERT OR REPLACE INTO refs VALUES (?,?,?,?,?)',
                            (actor, number, thread['id'], title, thread.get('cwd', '')))
            project = Path(thread.get('cwd') or '/').name or '未设置目录'
            lines.append(f'T{number:04d}｜{clean(title, 70)}\n  {clean(project, 60)}')
        self.db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?)',
                        (actor, result.get('nextCursor'), query))
        if len(lines) == 1:
            lines.append('未找到匹配会话。')
        lines.append('查看：会话查看 T0001；选择：会话选择 T0001')
        if result.get('nextCursor'):
            lines.append('更多：会话下一页')
        lines.append('范围：本机已入状态库、未归档的主会话；不含子代理。')
        return '\n'.join(lines)

    def _show(self, thread_id, label):
        result = self.api.request('thread/turns/list', {
            'threadId': thread_id, 'limit': 3, 'itemsView': 'full', 'sortDirection': 'desc'})
        texts = []
        for turn in result.get('data', []):
            for item in turn.get('items', []):
                if item.get('type') == 'agentMessage' and item.get('text'):
                    texts.append(item['text'])
            if texts:
                break
        body = clean('\n\n'.join(texts), 2200) if texts else '最近三轮没有可展示的助手文字结果。'
        return f'{label}\n最近已保存的助手输出（不代表任务已完成）：\n\n{body}\n\n只读；未恢复会话。实时运行状态未知。'


def main():
    os.umask(0o077)
    api = ReadOnlyAPI()
    try:
        raw = sys.stdin.read(32769)
        if len(raw) > 32768:
            print('输入过长，未执行。')
            return 0
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            print('输入格式无效，未执行。')
            return 0
        with contextlib.closing(Controller(BRIDGE_STATE, api)) as controller:
            print(controller.handle(envelope))
    except (Exception, KeyboardInterrupt):
        # Do not leak raw backend errors or credentials into the chat/log.
        print('会话总控暂时不可用或已超时；未启动科研任务，请稍后重试。')
    finally:
        api.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
