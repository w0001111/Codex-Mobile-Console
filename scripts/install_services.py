# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Install or remove only this installation's macOS login services."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from configure import ROOT, STATE


def main():
    if sys.platform != 'darwin' or sys.argv[1:] not in (['install'], ['remove']):
        raise SystemExit('macOS 用法：install_services.py install | remove')
    prefix = 'org.codex-mobile.' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    service_root = Path.home() / 'Library/LaunchAgents'
    domain = 'gui/' + str(os.getuid())
    roles = ('web', 'channel', 'tls', 'relay')
    if sys.argv[1] == 'remove':
        for role in roles:
            path = service_root / (prefix + '.' + role + '.plist')
            if path.exists():
                subprocess.run(['launchctl', 'bootout', domain + '/' + prefix + '.' + role], capture_output=True)
                path.unlink()
        print('已移除本安装目录对应的常驻服务，代码与私有数据保留。')
        return
    if not (STATE / 'owner.json').exists() or not (STATE / 'auth.sqlite3').exists():
        raise SystemExit('请先完成平台绑定和独立密码设置。')
    caddy = shutil.which('caddy')
    if not caddy or not all((STATE / 'network' / n).exists() for n in ('Caddyfile', 'relay.sh')):
        raise SystemExit('请先安装 Caddy、运行 configure_network.py，并完成手动公网连通检查。')
    commands = {
        'web': ['/bin/sh', str(ROOT / 'scripts/start-local.sh')],
        'channel': ['/bin/sh', str(ROOT / 'scripts/start-channel.sh')],
        'tls': [caddy, 'run', '--config', str(STATE / 'network/Caddyfile'), '--adapter', 'caddyfile'],
        'relay': ['/bin/sh', str(STATE / 'network/relay.sh')],
    }
    service_root.mkdir(parents=True, exist_ok=True)
    for role in roles:
        if (service_root / (prefix + '.' + role + '.plist')).exists():
            raise SystemExit('本安装已有常驻配置，拒绝覆盖；需要重装时先 remove。')
    logs = STATE / 'logs'; logs.mkdir(mode=0o700, exist_ok=True)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'MOBILE_STATE_DIR': str(STATE)}
    for key in ('CODEX_HOME', 'CONTROL_CODEX_BINARY'):
        if key in os.environ:
            env[key] = os.environ[key]
    for role, args in commands.items():
        label = prefix + '.' + role
        path = service_root / (label + '.plist')
        role_env = dict(env)
        if role == 'tls':
            role_env.update(XDG_DATA_HOME=str(STATE / 'caddy-data'), XDG_CONFIG_HOME=str(STATE / 'caddy-config'))
        data = {'Label': label, 'ProgramArguments': args, 'WorkingDirectory': str(ROOT),
                'EnvironmentVariables': role_env, 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 5,
                'StandardOutPath': str(logs / (role + '.log')), 'StandardErrorPath': str(logs / (role + '.error.log'))}
        with path.open('xb') as stream:
            plistlib.dump(data, stream)
        os.chmod(path, 0o600)
        subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
    print('本安装的 4 个服务已启动；它们在此 Mac 用户登录后运行。Mac 仍需保持联网和唤醒。')


if __name__ == '__main__':
    main()
