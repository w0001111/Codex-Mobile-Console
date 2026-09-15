# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Sign/verify immutable release bytes using OpenSSH SSHSIG, without executing the release."""
import argparse
import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

NAMESPACE = 'codex-mobile-release'
PRINCIPAL = 'release-author'


def public_key(path):
    text = Path(path).read_text(encoding='ascii').strip()
    if '\n' in text or '\r' in text:
        raise ValueError('Expected exactly one public key.')
    parts = text.split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('Expected an Ed25519 public key.')
    raw = base64.b64decode(parts[1], validate=True)
    # SSH wire format: string key type, string 32-byte public key.
    prefix = (11).to_bytes(4, 'big') + b'ssh-ed25519' + (32).to_bytes(4, 'big')
    if len(raw) != len(prefix) + 32 or not raw.startswith(prefix):
        raise ValueError('Invalid Ed25519 public key.')
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
    return ' '.join(parts[:2]), fingerprint


def verify(artifact, signature, key, trusted_fingerprint):
    key_text, actual = public_key(key)
    if not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', trusted_fingerprint):
        raise ValueError('Provide the independently trusted SHA256 fingerprint.')
    if not hmac.compare_digest(actual, trusted_fingerprint):
        raise ValueError('Public key does not match the trusted fingerprint.')
    with tempfile.TemporaryDirectory(prefix='release-verify-') as directory:
        allowed = Path(directory) / 'allowed_signers'
        allowed.write_text(f'{PRINCIPAL} namespaces="{NAMESPACE}" {key_text}\n')
        with Path(artifact).open('rb') as source:
            result = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', str(allowed),
                                     '-I', PRINCIPAL, '-n', NAMESPACE, '-s', str(Path(signature).resolve())],
                                    stdin=source, capture_output=True)
    if result.returncode:
        raise ValueError('Signature verification failed; do not install this artifact.')
    return actual


def sign(artifact, key, public, output):
    key = Path(key).resolve()
    root = Path(__file__).resolve().parent.parent
    if key.is_relative_to(root):
        raise ValueError('Private signing key must be outside the release source tree.')
    if not stat.S_ISREG(key.stat().st_mode) or stat.S_IMODE(key.stat().st_mode) & 0o077:
        raise ValueError('Private signing key must be a regular file with owner-only permissions.')
    _, fingerprint = public_key(public)
    if Path(output).exists() or Path(output).is_symlink():
        raise ValueError('Refusing to overwrite an existing signature.')
    with tempfile.TemporaryDirectory(prefix='release-sign-') as directory:
        signature = Path(directory) / 'signature'
        with Path(artifact).open('rb') as source, signature.open('wb') as target:
            # stdin mode avoids creating/replacing artifact.sig behind the caller's back.
            result = subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(key), '-n', NAMESPACE],
                                    stdin=source, stdout=target)
        if result.returncode:
            raise ValueError('Signing failed.')
        verify(artifact, signature, public, fingerprint)
        with Path(output).open('xb') as target:
            target.write(signature.read_bytes())
    return fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    fp = commands.add_parser('fingerprint')
    fp.add_argument('--public-key', type=Path, required=True)
    checking = commands.add_parser('verify')
    checking.add_argument('artifact', type=Path)
    checking.add_argument('--signature', type=Path, required=True)
    checking.add_argument('--public-key', type=Path, required=True)
    checking.add_argument('--trusted-fingerprint', required=True)
    signing = commands.add_parser('sign')
    signing.add_argument('artifact', type=Path)
    signing.add_argument('--private-key', type=Path, required=True)
    signing.add_argument('--public-key', type=Path, required=True)
    signing.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'fingerprint':
            print(public_key(args.public_key)[1])
        elif args.command == 'verify':
            print('Verified:', verify(args.artifact, args.signature, args.public_key, args.trusted_fingerprint))
        else:
            print('Signed and verified:', sign(args.artifact, args.private_key, args.public_key, args.output))
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
