# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Enrollment in this release must be local, private, and installation-specific."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import auth
import local_admin


class ReleaseSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / 'private'
        self.state_patch = patch.object(auth, 'STATE', self.state)
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.temp.cleanup()

    def configure(self, url):
        with patch('sys.argv', ['local_admin.py', 'configure']), patch('sys.stdin.isatty', return_value=True), \
                patch('builtins.input', side_effect=['weixin', 'synthetic-project', 'synthetic-session', 'synthetic-user', url]), \
                contextlib.redirect_stdout(io.StringIO()):
            local_admin.main()

    def test_configure_writes_only_new_private_installation(self):
        self.configure('https://console.example.test')
        self.assertEqual(local_admin.owner()['user_id'], 'synthetic-user')
        self.assertEqual(json.loads((self.state / 'public.json').read_text())['url'], 'https://console.example.test')
        for name in ('owner.json', 'public.json'):
            self.assertEqual(stat.S_IMODE((self.state / name).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertFalse((self.state / 'auth.sqlite3').exists())

    def test_invalid_origin_does_not_enroll(self):
        for url in ('http://console.example.test', 'https://console.example.test/path',
                    'https://user:synthetic@console.example.test', 'https://console.example.test?x=1'):
            with self.assertRaises(SystemExit):
                self.configure(url)
            self.assertFalse((self.state / 'owner.json').exists())

    def test_existing_identity_is_not_overwritten(self):
        self.configure('https://console.example.test')
        before = (self.state / 'owner.json').read_bytes()
        with self.assertRaises(SystemExit):
            self.configure('https://different.example.test')
        self.assertEqual(before, (self.state / 'owner.json').read_bytes())

    def test_noninteractive_enrollment_and_pair_output_rejected(self):
        for command in ('configure', 'set-password', 'pair'):
            with patch('sys.argv', ['local_admin.py', command]), patch('sys.stdin.isatty', return_value=False), \
                    patch('sys.stdout.isatty', return_value=False), self.assertRaises(SystemExit):
                local_admin.main()
        self.assertFalse(self.state.exists())
