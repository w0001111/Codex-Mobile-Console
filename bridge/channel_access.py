# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Installation-scoped admission at the trusted cc-connect stdin boundary."""
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from paths import STATE

FIELDS = ('project', 'platform', 'session_key', 'user_id')


def valid_platform(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value) is not None


def write_private(directory, name, value):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    temporary = directory / (name + '.' + secrets.token_hex(6) + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / name)
    finally:
        temporary.unlink(missing_ok=True)


def begin_binding(expected, directory=STATE):
    if not valid_platform(expected.get('platform')) or any(
        not isinstance(expected.get(k), str) or not expected[k].strip() or len(expected[k]) > 1024
        for k in ('project', 'user_id')
    ) or expected['user_id'] == '*':
        raise ValueError('需要自己的平台、项目及用户 ID。')
    directory = Path(directory)
    if (directory / 'owner.json').exists():
        raise ValueError('已有绑定身份，拒绝覆盖。切换平台请使用新的部署目录。')
    token = secrets.token_hex(16).upper()
    write_private(directory, 'binding.json', {
        'expected': {k: expected[k] for k in ('project', 'platform', 'user_id')},
        'digest': hashlib.sha256(token.encode()).hexdigest(), 'expires': time.time() + 600,
    })
    return token


def admit(envelope, directory=STATE):
    """Return None for the exact owner; otherwise a safe, handled reply.

    The platform supplies identities, never chat text. No HTTP route calls this.
    The binding token can claim only the locally selected project/platform/user.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(directory / 'binding.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        owner_file = directory / 'owner.json'
        if owner_file.exists():
            owner = json.loads(owner_file.read_text())
            if all(isinstance(owner.get(k), str) and owner[k] and owner[k] == envelope.get(k) for k in FIELDS):
                return None
            return '此消息身份或会话未绑定本控制台，未读取或发送任务内容。'
        pending = json.loads((directory / 'binding.json').read_text())
        if pending['expires'] < time.time():
            return '首次绑定码已过期，请在 Mac 运行 scripts/configure.py renew-binding 重新生成。'
        expected = pending['expected']
        if any(envelope.get(k) != expected[k] for k in ('project', 'platform', 'user_id')):
            return '此消息身份未获本控制台授权。'
        args = envelope.get('args', [])
        text = args[0].strip() if len(args) == 1 and isinstance(args[0], str) else ''
        match = re.fullmatch(r'绑定控制台\s+([A-Fa-f0-9]{32})', text)
        if not match or envelope.get('has_attachments') or not isinstance(envelope.get('session_key'), str) or not envelope['session_key']:
            return '请在私聊中发送 Mac 设置向导显示的“绑定控制台 …”命令，完成首次绑定。'
        digest = hashlib.sha256(match[1].upper().encode()).hexdigest()
        if not hmac.compare_digest(digest, pending['digest']):
            return '首次绑定码无效，请核对 Mac 设置向导。'
        write_private(directory, 'owner.json', {k: envelope[k] for k in FIELDS})
        (directory / 'binding.json').unlink()
        return '控制台身份已绑定。请回到 Mac 设置独立网页登录密码，然后在本会话发送“界面”获取登录码。'
    except (OSError, ValueError, KeyError, TypeError):
        return '控制台尚未完成本机配置，未读取或发送任务内容。'
    finally:
        os.close(fd)
