# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Real cryptographic checks using disposable keys; no operator secrets or network."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import package_release
import release_signature as signing


class ReleaseSignatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='signature-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.make_key('author')
        self.public = self.key.with_suffix('.pub')
        self.fp = signing.public_key(self.public)[1]
        self.artifact = self.root / 'release.zip'
        self.artifact.write_bytes(b'example immutable release bytes')
        self.sig = self.root / 'release.zip.sig'
        signing.sign(self.artifact, self.key, self.public, self.sig)

    def make_key(self, name):
        key = self.root / name
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', '', '-f', str(key)], check=True)
        return key

    def test_valid_signature_and_openssh_fingerprint(self):
        self.assertEqual(signing.verify(self.artifact, self.sig, self.public, self.fp), self.fp)
        result = subprocess.check_output(['ssh-keygen', '-l', '-E', 'sha256', '-f', str(self.public)], text=True)
        self.assertEqual(result.split()[1], self.fp)

    def test_tampered_artifact_rejected(self):
        self.artifact.write_bytes(self.artifact.read_bytes() + b' modified')
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            signing.verify(self.artifact, self.sig, self.public, self.fp)

    def test_wrong_key_and_substituted_package_rejected(self):
        other = self.make_key('other')
        other_public = other.with_suffix('.pub')
        with self.assertRaisesRegex(ValueError, 'trusted fingerprint'):
            signing.verify(self.artifact, self.sig, other_public, self.fp)
        other_fp = signing.public_key(other_public)[1]
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            signing.verify(self.artifact, self.sig, other_public, other_fp)

    def test_wrong_namespace_rejected(self):
        with self.artifact.open('rb') as source, self.sig.open('wb') as dest:
            subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(self.key), '-n', 'other-purpose'],
                           stdin=source, stdout=dest, check=True)
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            signing.verify(self.artifact, self.sig, self.public, self.fp)

    def test_existing_signature_not_overwritten(self):
        original = self.sig.read_bytes()
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            signing.sign(self.artifact, self.key, self.public, self.sig)
        self.assertEqual(self.sig.read_bytes(), original)

    def test_mismatched_signing_key_leaves_no_output(self):
        other = self.make_key('other')
        target = self.root / 'new.sig'
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            signing.sign(self.artifact, other, self.public, target)
        self.assertFalse(target.exists())

    def test_world_readable_private_key_rejected(self):
        self.key.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'owner-only'):
            signing.sign(self.artifact, self.key, self.public, self.root / 'new.sig')

    def test_private_key_in_source_tree_rejected(self):
        with patch.object(signing, '__file__', str(self.root / 'scripts' / 'release_signature.py')):
            with self.assertRaisesRegex(ValueError, 'outside'):
                signing.sign(self.artifact, self.key, self.public, self.root / 'new.sig')

    def test_fingerprint_required_and_public_key_single_line(self):
        with self.assertRaises(ValueError):
            signing.verify(self.artifact, self.sig, self.public, '')
        self.public.write_bytes(self.public.read_bytes() * 2)
        with self.assertRaises(ValueError):
            signing.public_key(self.public)

    def test_privacy_scanner_only_allows_registered_release_public_key(self):
        import json
        public = self.root / 'release-signing.pub'
        public.write_text(signing.public_key(self.public)[0] + '\n')
        (self.root / 'AUTHOR.json').write_text(json.dumps({'signingFingerprint': self.fp}))
        with patch.object(package_release, 'ROOT', self.root):
            self.assertEqual(package_release.inspect(public.name, public.read_bytes(), []), [])
            self.assertTrue(package_release.inspect('README.md', public.read_bytes(), []))
            self.assertTrue(package_release.inspect(public.name, self.key.read_bytes(), []))
            (self.root / 'AUTHOR.json').write_text(json.dumps({'signingFingerprint': 'wrong'}))
            self.assertTrue(package_release.inspect(public.name, public.read_bytes(), []))


    def test_private_deny_list_accepts_short_labels_and_rejects_too_short_values(self):
        import json
        path = self.root / 'private-deny.json'
        value = '示例机密'
        path.write_text(json.dumps([value]))
        denied = package_release.load_denied(path)
        self.assertEqual(denied, [value])
        self.assertEqual(package_release.inspect('fixture.py', value.encode(), denied),
                         [{'file': 'fixture.py', 'rule': 'operator_private_value'}])
        self.assertEqual(package_release.inspect('fixture.py', b'generic example', denied), [])
        for invalid in (['abc'], ['    '], [1234], {'name': value}):
            path.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError):
                package_release.load_denied(path)


if __name__ == '__main__':
    unittest.main()
