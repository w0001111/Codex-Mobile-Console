# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Trusted messaging command entry. Not exposed as an HTTP pairing-code issuer."""
import json
from pathlib import Path
import sys
from auth import issue,STATE
from adapter import base_envelope

def reply(envelope):
    env=base_envelope(envelope)
    try:
        config=json.loads((STATE/'public.json').read_text())
        if not config.get('ready') or not str(config.get('url','')).startswith('https://'):raise ValueError()
    except (OSError,ValueError,KeyError):
        return '手机任务界面尚未发布。现有消息平台菜单与任务直聊仍可使用。'
    code=issue(env)
    display='-'.join(code[i:i+5] for i in range(0,len(code),5))
    return ('手机任务管理\n'+config['url']+'\n\n配对码：'+display+'\n'
            '打开页面后输入配对码＋独立密码；配对码10分钟内有效，仅可使用一次。\n'
            '独立密码在 Mac 本机设置或重设，请勿在消息平台发送密码。\n'
            '登录后网页直接控制本地 Codex；网页切换与消息平台当前任务各自独立。\n'
            '这是你的私有控制台入口；Mac 和 Codex 桌面需要保持运行。')
if __name__=='__main__':
    try:
        raw=sys.stdin.read(32769)
        if len(raw)>32768:raise ValueError()
        print(reply(json.loads(raw)))
    except Exception:print('手机界面入口暂不可用，请稍后再试。')
