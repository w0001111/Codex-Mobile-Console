# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Create a new, private single-owner deployment for a chosen cc-connect platform."""
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'bridge'))
from paths import STATE
from channel_access import begin_binding, write_private

PLATFORMS = ('weixin', 'feishu', 'lark', 'telegram', 'discord', 'slack', 'dingtalk',
             'wecom', 'qq', 'qqbot', 'line', 'weibo', 'max', 'matrix', 'webex', 'wps-xiezuo')
HINTS = {
    'telegram': 'token', 'discord': 'token', 'slack': 'bot_token, app_token',
    'feishu': 'app_id, app_secret', 'lark': 'app_id, app_secret',
    'dingtalk': 'client_id, client_secret', 'qqbot': 'app_id, app_secret',
    'weixin': '可留空，稍后用 weixin-login.sh 扫码',
}


def scalar(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value, allow_nan=False)
    if isinstance(value, list):
        return '[' + ', '.join(scalar(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(scalar(k) + ' = ' + scalar(v) for k, v in value.items()) + '}'
    raise ValueError('平台选项不能包含 null 或非 JSON 类型。')


def make_config(root, state, platform, project, user, options):
    if platform not in PLATFORMS or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', project):
        raise ValueError('平台或项目名无效。')
    if (not user and platform != 'weixin') or any(c in user for c in ('*', ',', '\n', '\r')):
        raise ValueError('需要一个明确的用户 ID，不能用通配符或名单。')
    if not isinstance(options, dict):
        raise ValueError('平台选项需要 JSON 对象。')
    options = dict(options)
    options['allow_from'] = user
    lines = ['language = "zh"', 'data_dir = ' + scalar(str(state / 'cc-connect')),
             '[management]', 'enabled = false', '[bridge]', 'enabled = false']
    for name, extra in (('control', []), ('console-router', ['--route-message'])):
        lines += ['[[commands]]', 'name = '+scalar(name),
                  'description = "Local desktop console"',
                  'argv = '+scalar([str(root / '.venv/bin/python'), str(root / 'bridge/wechat_entry.py')] + extra),
                  'work_dir = '+scalar(str(root))]
    lines += ['[[projects]]', 'name = '+scalar(project), 'admin_from = '+scalar(user),
              'disabled_commands = ["upgrade", "restart", "shell", "show", "dir", "web", "commands"]',
              '[projects.agent]', 'type = "codex"', '[projects.agent.options]',
              'work_dir = '+scalar(str(state / 'assistant-workspace')), 'mode = "suggest"',
              '[[projects.platforms]]', 'type = '+scalar(platform), '[projects.platforms.options]']
    lines += [scalar(key)+' = '+scalar(value) for key, value in options.items()]
    content = '\n'.join(lines) + '\n'
    tomllib.loads(content)
    return content


def private_text(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)


def scan_weixin(project):
    subprocess.run([str(ROOT / 'bin/cc-connect'), 'weixin', 'setup', '--config',
                    str(STATE / 'cc-connect.toml'), '--set-allow-from-empty'], check=True)
    scanned = tomllib.loads((STATE / 'cc-connect.toml').read_text())
    options = scanned['projects'][0]['platforms'][0]['options']
    user = options.get('allow_from', '')
    content = make_config(ROOT, STATE, 'weixin', project, user, options)
    if not user:
        raise ValueError('扫码未返回明确的用户 ID。')
    temporary = STATE / ('cc-connect.' + secrets.token_hex(6) + '.tmp')
    try:
        private_text(temporary, content)
        os.replace(temporary, STATE / 'cc-connect.toml')
    finally:
        temporary.unlink(missing_ok=True)
    return user, options


def main():
    os.umask(0o077)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit('请在 Mac 本机交互终端运行；不把凭据或绑定码写入日志。')
    if sys.argv[1:] == ['renew-binding']:
        if (STATE / 'owner.json').exists():
            raise SystemExit('已完成绑定，拒绝重新绑定其他身份。')
        if (STATE / 'binding.json').exists():
            expected = json.loads((STATE / 'binding.json').read_text())['expected']
        else:
            project = tomllib.loads((STATE / 'cc-connect.toml').read_text())['projects'][0]
            platform = project['platforms'][0]['type']
            user = project.get('admin_from', '')
            if platform == 'weixin' and not user:
                user, _ = scan_weixin(project['name'])
            expected = {'platform': platform, 'project': project['name'], 'user_id': user}
        token = begin_binding(expected, STATE)
        print('请在机器人私聊发送：绑定控制台 ' + token)
        return
    if sys.argv[1:]:
        raise SystemExit('用法：configure.py [renew-binding]')
    if any((STATE / name).exists() for name in ('owner.json', 'cc-connect.toml', 'binding.json')):
        raise SystemExit('已有配置，拒绝覆盖。更换平台请解压到新目录；码过期可用 renew-binding。')
    print('选择消息平台：' + ', '.join(PLATFORMS))
    platform = input('platform: ').strip()
    if platform not in PLATFORMS:
        raise SystemExit('当前固定上游版本未包含这个平台。')
    project = input('项目名称 [my-console]: ').strip() or 'my-console'
    user = input('你自己的平台用户 ID（微信可留空，扫码后自动获取；其他平台从资料或已有机器人 /whoami 获取）: ').strip()
    origin = input('自己的 HTTPS 地址（例如 https://console.example.test）: ').strip().rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit('需要 HTTPS 来源地址，不含路径、账号和查询参数。')
    print('平台凭据由你在相应平台创建机器人后取得。字段说明见 .build/upstream-reference/config.example.toml。')
    print('常见字段：' + HINTS.get(platform, '按上游对应平台说明填写'))
    print('输入平台 options 的 JSON 对象（隐藏输入，回车代表空对象），或输入 @ 加你自己的私有 TOML 文件路径。')
    raw = getpass.getpass('平台 options: ').strip()
    if raw.startswith('@'):
        options = tomllib.loads(Path(raw[1:]).expanduser().read_text())
    else:
        options = json.loads(raw or '{}')
    content = make_config(ROOT, STATE, platform, project, user, options)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    (STATE / 'assistant-workspace').mkdir(mode=0o700, exist_ok=True)
    private_text(STATE / 'cc-connect.toml', content)
    write_private(STATE, 'public.json', {'url': origin, 'ready': True})
    if platform == 'weixin' and not user:
        # The initial config denies admin access. The upstream setup command
        # obtains the scanned account's authenticated ID without starting an Agent.
        user, options = scan_weixin(project)
    token = begin_binding({'platform': platform, 'project': project, 'user_id': user}, STATE)
    print('配置已写入本机私有目录。')
    if platform == 'weixin' and not options.get('token'):
        print('先在另一个终端运行：sh scripts/weixin-login.sh')
    print('在另一个终端运行：sh scripts/start-channel.sh')
    print('然后在机器人私聊发送：绑定控制台 ' + token)
    print('绑定码 10 分钟有效。收到成功回执后：.venv/bin/python mobile-ui/local_admin.py set-password')
    print('最后启动网页：sh scripts/start-local.sh；按 README 配置 HTTPS 和手机访问。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError):
        raise SystemExit('配置无效或文件不可读取；未打印任何平台凭据。请核对输入。')
