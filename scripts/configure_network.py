# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Generate private network configuration for HTTPS over the operator's SSH relay."""
import os
from pathlib import Path
import re
import shlex
import sys
import json
import ipaddress
import tomllib
from urllib.parse import urlsplit
from configure import ROOT, STATE, private_text


def caddy_config(host, callback=None):
    # Restrict generated Caddy tokens to a hostname. No config text injection.
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?', host):
        raise ValueError('需要有效的域名。')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('自动证书模板需要自己的域名；IP 证书需单独配置。')
    routes = '    reverse_proxy 127.0.0.1:9840\n'
    if callback:
        path, port = callback
        if not re.fullmatch(r'/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+', path) or path.split('/')[1] in ('api', 'assets') or not 1024 <= int(port) <= 65535:
            raise ValueError('回调路径或端口无效。')
        routes = ('    handle ' + path + ' {\n        reverse_proxy 127.0.0.1:' + str(int(port)) +
                  '\n    }\n    handle {\n        reverse_proxy 127.0.0.1:9840\n    }\n')
    return '''{
    admin off
    http_port 9080
    https_port 9443
    auto_https disable_redirects
}
''' + host + ''' {
    bind 127.0.0.1
    tls {
        issuer acme {
            disable_http_challenge
        }
    }
''' + routes + '}\n'


def main():
    os.umask(0o077)
    if not sys.stdin.isatty():
        raise SystemExit('请在本机终端运行。')
    parsed = urlsplit(json.loads((STATE / 'public.json').read_text())['url'])
    if parsed.port not in (None, 443):
        raise ValueError('此网络模板使用标准 HTTPS 443 端口。')
    host = parsed.hostname
    print('将域名解析到你自己的服务器，并在服务器防火墙开放 TCP 443。')
    print('本模板要求服务器可通过 SSH 密钥登录，并允许 loopback 远程转发。')
    alias = input('已在自己的 SSH 配置中设置并验证的服务器别名（例如 console-relay）: ').strip()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', alias):
        raise ValueError('请使用一个有效的 SSH Host 别名。')
    directory = STATE / 'network'
    directory.mkdir(mode=0o700, exist_ok=True)
    platform = tomllib.loads((STATE / 'cc-connect.toml').read_text())['projects'][0]['platforms'][0]
    options = platform.get('options', {})
    callback = None
    if platform['type'] == 'line':
        callback = (options.get('callback_path', '/callback'), options.get('port', '8080'))
    elif platform['type'] == 'wecom' and options.get('mode') != 'websocket':
        callback = (options.get('callback_path', '/wecom/callback'), options.get('port', '8081'))
    private_text(directory / 'Caddyfile', caddy_config(host, callback))
    args = ['/usr/bin/ssh', '-NT', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
            '-R', '127.0.0.1:19443:127.0.0.1:9443', alias]
    private_text(directory / 'relay.sh', '#!/bin/sh\nset -eu\nexec ' + shlex.join(args) + '\n')
    print('已生成私有 Caddyfile 和 SSH 隧道脚本。')
    print('服务器端先执行 deploy/install-relay.example.sh；本机按 README 启动 Caddy 与隧道。')
    print('配置文件已存在时本工具拒绝覆盖，便于保留正在使用的网络配置。')
    if callback:
        print('在平台后台登记并验证回调地址：https://' + host + callback[0])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError):
        raise SystemExit('网络配置未完成：请检查域名、SSH 别名和已有配置文件。')
