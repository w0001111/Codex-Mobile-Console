# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Multi-platform binding and auth regressions, without any live message sends."""
import contextlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import tomllib
import sys
import unittest
from unittest.mock import patch

import adapter
import auth
import channel_access
from wechat_entry import identity

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('release_configure', ROOT / 'scripts/configure.py')
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class MultiChannelTests(unittest.TestCase):
    def envelope(self, platform='telegram', **extra):
        return dict(version=1, project='my-console', platform=platform, user_id='owner',
                    session_key='private-chat', message_id='unique-message', args=[], **extra)

    def test_all_pinned_platforms_bind_exact_owner_and_session(self):
        for platform in configure.PLATFORMS:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                env = self.envelope(platform)
                state = Path(temp)
                token = channel_access.begin_binding(env, state)
                self.assertNotIn(token, (state / 'binding.json').read_text())
                reply = channel_access.admit({**env, 'args': ['绑定控制台 ' + token]}, state)
                self.assertIn('已绑定', reply)
                self.assertIsNone(channel_access.admit(env, state))
                for field in ('project', 'platform', 'user_id', 'session_key'):
                    self.assertIsNotNone(channel_access.admit({**env, field: 'other'}, state))
                self.assertFalse((state / 'binding.json').exists())
                self.assertEqual((state / 'owner.json').stat().st_mode & 0o777, 0o600)

    def test_token_cannot_bind_wrong_user_channel_or_expired(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp); env = self.envelope()
            token = channel_access.begin_binding(env, state)
            command = {**env, 'args': ['绑定控制台 ' + token]}
            for field in ('project', 'platform', 'user_id'):
                channel_access.admit({**command, field: 'other'}, state)
                self.assertFalse((state / 'owner.json').exists())
            channel_access.admit({**command, 'has_attachments': True}, state)
            self.assertFalse((state / 'owner.json').exists())
            pending = json.loads((state / 'binding.json').read_text())
            pending['expires'] = time.time() - 1
            channel_access.write_private(state, 'binding.json', pending)
            self.assertIn('过期', channel_access.admit(command, state))
            self.assertFalse((state / 'owner.json').exists())

    def test_configuration_missing_never_admits(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNotNone(channel_access.admit(self.envelope(), Path(temp)))

    def test_actor_and_web_identity_are_platform_scoped(self):
        identities = []
        for platform in configure.PLATFORMS:
            env = self.envelope(platform)
            identities.append(identity(env)[0])
            self.assertEqual(auth.web_identity(env)['platform'], platform)
            self.assertNotEqual(adapter.identity_key(auth.web_identity(env)), adapter.identity_key(env))
        self.assertEqual(len(set(identities)), len(identities))
        for platform in ('', '../telegram', 'Telegram', 'telegram\n', '*'):
            with self.assertRaises(Exception):
                identity(self.envelope(platform))

    def test_generated_toml_all_platforms_fixed_argv_and_owner(self):
        for platform in configure.PLATFORMS:
            content = configure.make_config(Path('/tmp/synthetic console'), Path('/tmp/synthetic state'),
                platform, 'my-console', 'owner', {'token': 'synthetic-only', 'nested': {'value': 'quote"\ntext'}, 'allow_from': '*'})
            result = tomllib.loads(content)
            self.assertFalse(result['management']['enabled'])
            self.assertFalse(result['bridge']['enabled'])
            project = result['projects'][0]
            self.assertEqual(project['admin_from'], 'owner')
            self.assertEqual(project['platforms'][0]['options']['allow_from'], 'owner')
            command = result['commands'][1]
            self.assertEqual(command['name'], 'console-router')
            self.assertEqual(command['argv'][-1], '--route-message')
            self.assertNotIn('exec', command)

    def test_wildcard_user_rejected(self):
        for user in ('*', 'one,two', 'user\nadmin'):
            with self.assertRaises(ValueError):
                configure.make_config(ROOT, ROOT/'private', 'telegram', 'my-console', user, {})

    def test_weixin_scan_recovers_authenticated_user_without_manual_session(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            def scanned(*args, **kwargs):
                content = configure.make_config(ROOT, state, 'weixin', 'my-console', 'scanned-user', {'token':'synthetic-token'})
                (state/'cc-connect.toml').write_text(content)
            with patch.object(configure, 'STATE', state), patch.object(configure.subprocess, 'run', side_effect=scanned):
                user, options = configure.scan_weixin('my-console')
            self.assertEqual(user, 'scanned-user')
            self.assertEqual(tomllib.loads((state/'cc-connect.toml').read_text())['projects'][0]['admin_from'], user)
            self.assertEqual((state/'cc-connect.toml').stat().st_mode & 0o777, 0o600)

    def test_network_routes_cannot_override_auth_paths_or_inject_config(self):
        sys.path.insert(0, str(ROOT/'scripts'))
        from configure_network import caddy_config
        normal = caddy_config('console.example.test')
        self.assertIn('admin off', normal)
        self.assertIn('bind 127.0.0.1', normal)
        self.assertIn('https_port 9443', normal)
        self.assertIn('handle /callback', caddy_config('console.example.test', ('/callback',8080)))
        for host, callback in [('bad\nconfig',None),('127.0.0.1',None),('console.example.test',('/api/pair',8080)),
                               ('console.example.test',('/callback',22)),('console.example.test',('/*',8080))]:
            with self.assertRaises(ValueError):
                caddy_config(host, callback)

    def test_platform_pair_code_still_requires_independent_password(self):
        env = self.envelope('feishu')
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            auth.set_password(env, 'SyntheticIndependentPassword', state)
            code = auth.issue(env, state)
            # Test the real stored principal, with no network or model access.
            with contextlib.closing(auth.connect(state)) as db:
                identity_json = db.execute('SELECT identity FROM pairs WHERE digest=?', (auth.digest(code),)).fetchone()[0]
                source = json.loads(identity_json)
                self.assertEqual(source['platform'], 'feishu')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM web_passwords').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
