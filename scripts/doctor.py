# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Read-only deployment checks; never send a model turn or print credentials."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tomllib
import urllib.error
import urllib.request
from configure import ROOT, STATE, PLATFORMS


def main():
    if sys.argv[1:] not in ([], ['--public']):
        raise SystemExit('用法：doctor.py [--public]')
    results = []
    def check(label, operation):
        try:
            ok = bool(operation())
        except Exception:
            ok = False
        results.append(ok)
        print(('通过：' if ok else '待处理：') + label)
    check('Python 3.11+', lambda: sys.version_info >= (3, 11))
    check('网页构建文件', lambda: (ROOT/'mobile-ui/frontend/dist/index.html').is_file())
    def binary_ok():
        build = json.loads((ROOT/'bin/build.json').read_text())
        return hashlib.sha256((ROOT/'bin/cc-connect').read_bytes()).hexdigest() == build['binary_sha256']
    check('本安装 cc-connect 程序校验', binary_ok)
    check('Codex CLI 可执行', lambda: shutil.which(os.environ.get('CONTROL_CODEX_BINARY','codex')))
    check('Codex 桌面 IPC 可用', lambda: (Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'ipc/ipc.sock').is_socket())
    def identity_ok():
        owner = json.loads((STATE/'owner.json').read_text())
        config = tomllib.loads((STATE/'cc-connect.toml').read_text())
        project = config['projects'][0]
        platform = project['platforms'][0]
        return (platform['type'] in PLATFORMS and owner['platform']==platform['type']
                and owner['project']==project['name'] and owner['user_id']==project['admin_from']
                and platform['options']['allow_from']==owner['user_id'] and bool(owner['session_key']))
    check('平台身份、项目和私聊绑定', identity_ok)
    def password_ok():
        sys.path.insert(0,str(ROOT/'mobile-ui'))
        import adapter
        owner = json.loads((STATE/'owner.json').read_text())
        with sqlite3.connect((STATE/'auth.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            return db.execute('SELECT 1 FROM web_passwords WHERE actor=?',(adapter.identity_key(owner),)).fetchone()
    check('已设置本绑定身份的独立密码', password_ok)
    if '--public' in sys.argv:
        def public_ok():
            origin = json.loads((STATE/'public.json').read_text())['url']
            if not origin.startswith('https://'):
                return False
            try:
                urllib.request.urlopen(origin+'/api/tasks',timeout=15)
            except urllib.error.HTTPError as error:
                return error.code==401
            return False
        check('公网证书、连通性及未登录访问拦截', public_ok)
    print('此检查不发送任务消息；首次部署仍需用自己的测试任务核对完整收发。')
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
