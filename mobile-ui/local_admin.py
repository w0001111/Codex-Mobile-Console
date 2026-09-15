# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Local operator enrollment and recovery; never exposed as an HTTP route."""
import getpass
import json
import os
import sys
from urllib.parse import urlsplit
import auth
# adapter initializes the sibling bridge import path.
import adapter
from channel_access import valid_platform


def owner():
    value = json.loads((auth.STATE / 'owner.json').read_text())
    keys = ('project', 'platform', 'session_key', 'user_id')
    if (not isinstance(value, dict) or set(value) != set(keys)
            or not valid_platform(value.get('platform'))
            or any(not isinstance(value.get(k), str) or not value[k].strip() for k in keys)):
        raise ValueError('本机身份配置无效，请运行 configure。')
    return value


def write_private(name, value):
    auth.STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(auth.STATE, 0o700)
    destination = auth.STATE / name
    temporary = auth.STATE / (name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    if len(sys.argv) != 2 or sys.argv[1] not in ('configure', 'pair', 'revoke', 'set-password'):
        raise SystemExit('用法：local_admin.py configure | pair | revoke | set-password')
    command = sys.argv[1]
    if command in ('configure', 'set-password') and not sys.stdin.isatty():
        raise SystemExit('请在本机终端交互操作，不通过参数或管道传递身份、密码。')
    if command == 'configure':
        if (auth.STATE / 'owner.json').exists():
            raise SystemExit('已有身份配置，拒绝覆盖。更换部署身份请使用新的空状态目录。')
        print('填写你自己的可信消息平台入口身份，须与机器人传入的身份字段完全一致。')
        value = {'platform': input('platform (如 weixin/feishu/telegram): ').strip()}
        if not valid_platform(value['platform']):
            raise SystemExit('平台标识无效。')
        for key in ('project', 'session_key', 'user_id'):
            value[key] = input(key + ': ').strip()
            if not value[key] or len(value[key]) > 1024:
                raise SystemExit('身份字段为空或过长。')
        url = input('已配置的 HTTPS 控制台地址（不含路径）: ').strip().rstrip('/')
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise SystemExit('需要完整 HTTPS 来源地址，不含账号、路径、查询或片段。')
        write_private('owner.json', value)
        write_private('public.json', {'url': url, 'ready': True})
        print('已写入本机私有状态目录。接下来运行 set-password 设置独立密码。')
    elif command == 'set-password':
        source = owner()
        print('设置独立网页登录密码（9–128 字符），请勿复用其他账号或服务器密码。')
        password = getpass.getpass('新密码：')
        if password != getpass.getpass('再次输入：'):
            raise SystemExit('两次输入不一致，未修改。')
        auth.set_password(source, password)
        print('密码已设置，旧网页登录和配对码已撤销。通过可信消息平台入口获取新的配对码。')
    elif command == 'pair':
        if not sys.stdout.isatty():
            raise SystemExit('请在本机终端查看配对码，避免重定向到公开日志。')
        config = json.loads((auth.STATE / 'public.json').read_text())
        print('控制台：' + config['url'])
        print('本机恢复用一次性配对码（10 分钟有效）：' + auth.issue(owner()))
    else:
        auth.revoke_all()
        print('本部署的全部网页登录和未使用配对码已撤销。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError):
        raise SystemExit('本机配置无效或暂不可读取，请核对私有配置；未输出任何凭据。')
