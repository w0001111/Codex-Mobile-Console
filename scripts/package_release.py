# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Allowlist export with privacy checks; never package a working directory wholesale."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import zipfile
import struct
import zlib
from release_signature import public_key

ROOT = Path(__file__).resolve().parent.parent
TOP = {'.gitignore', '.env.example', 'README.md', 'USAGE.md', 'INSTALL.md', 'TECHNICAL.md', 'PRIVACY.md', 'RELEASE_REPORT.json', 'VERSION', 'THIRD_PARTY.md', 'THIRD_PARTY_LICENSES.md', 'LICENSE', 'AUTHOR.json', 'AUTHORS.md', 'SIGNING.md', 'release-signing.pub'}
BLOCKED = {'private', '.git', '.venv', 'node_modules', '__pycache__', '.ssh', 'experiments', '.build', 'bin'}
PATTERNS = {
    'personal_home_path': re.compile(r'/Users/[A-Za-z0-9_.-]+/'),
    'personal_volume_path': re.compile(r'/Volumes/[\w .-]+/'),
    'historical_task_id': re.compile(r'\b(?:01a[0-9a-f]{5}|019f[0-9a-f]{4})-[0-9a-f-]{27,}\b'),
    'legacy_password_pattern': re.compile(r'(?i)\bWei\d{6,}'),
    'private_key': re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    'api_key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    'ssh_public_key': re.compile(r'ssh-(?:rsa|ed25519)\s+[A-Za-z0-9+/]{32,}'),
    'credential_in_url': re.compile(r'https?://[^\s/]+:[^\s/]+@'),
}
IPV4 = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
SCREENSHOTS = {'login.png', 'overview.png', 'conversation.png', 'logins.png'}


def reviewed_screenshot(name, data):
    """Allow only the reviewed demo images, pinned by hash; no PNG metadata chunks.

    This is an integrity gate, not image OCR. Privacy review must happen when
    generating synthetic fixtures and visually reviewing the resulting pixels.
    """
    path = Path(name)
    if path.parent.as_posix() != 'docs/screenshots' or path.name not in SCREENSHOTS:
        return False
    try:
        manifest = json.loads((ROOT / 'docs/screenshots/manifest.json').read_text())
        if manifest['contains_real_user_data'] is not False:
            return False
        entry = manifest['screenshots'][path.name]
        if hashlib.sha256(data).hexdigest() != entry['sha256'] or data[:8] != b'\x89PNG\r\n\x1a\n':
            return False
        offset, kinds = 8, []
        while offset < len(data):
            size = struct.unpack('>I', data[offset:offset+4])[0]
            end = offset + size + 12
            kind = data[offset+4:offset+8]
            if end > len(data) or kind not in (b'IHDR', b'IDAT', b'IEND'):
                return False
            crc = struct.unpack('>I', data[end-4:end])[0]
            if zlib.crc32(data[offset+4:end-4]) != crc:
                return False
            kinds.append(kind)
            offset = end
        if not kinds or kinds[0] != b'IHDR' or kinds[-1] != b'IEND' or kinds.count(b'IHDR') != 1 or kinds.count(b'IEND') != 1:
            return False
        width, height = struct.unpack('>II', data[16:24])
        return b'IDAT' in kinds and width == entry['width'] and height == entry['height'] and 0 < width <= 2000 and 0 < height <= 6000
    except (OSError, ValueError, KeyError, TypeError, struct.error):
        return False


def allowed(path):
    if any(part in BLOCKED for part in path.parts):
        return False
    if len(path.parts) == 1:
        return path.name in TOP
    if path.parent.as_posix() == 'docs/screenshots':
        return path.name in SCREENSHOTS or path.name == 'manifest.json'
    if path.parts[0] == 'patches':
        return len(path.parts) == 2 and path.name in ('cc-connect.patch', 'cc-connect.json')
    if path.parts[0] == 'bridge':
        return len(path.parts) == 2 and path.suffix == '.py'
    if path.parts[0] == 'scripts':
        return len(path.parts) == 2 and path.suffix in ('.sh', '.py')
    if path.parts[0] == 'deploy':
        return len(path.parts) == 2 and (path.name.endswith('.example') or '.example.' in path.name)
    if path.parts[0] != 'mobile-ui':
        return False
    if len(path.parts) == 2:
        return path.suffix in ('.py', '.command') or path.name == 'requirements.lock'
    if path.parts[1] != 'frontend':
        return False
    if len(path.parts) == 3:
        return path.name in {'index.html', 'package.json', 'package-lock.json', 'test-api.mjs'}
    if path.parts[2] in ('src', 'dist'):
        return path.suffix in ('.js', '.jsx', '.css', '.html', '.svg')
    return False


def inspect(name, data, denied):
    if name.startswith('docs/screenshots/') and name.endswith('.png'):
        return [] if reviewed_screenshot(name, data) else [{'file': name, 'rule': 'unreviewed_or_invalid_screenshot'}]
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return [{'file': name, 'rule': 'unexpected_binary'}]
    # Exact reserved-domain negative fixture (also mentioned in this scanner).
    # No other embedded-credential URL is exempted.
    checked = text.replace('https://user:synthetic@console.example.test', 'SYNTHETIC_NEGATIVE_URL')
    public_release_key = False
    if name == 'release-signing.pub':
        try:
            key, fingerprint = public_key(ROOT / name)
            metadata = json.loads((ROOT / 'AUTHOR.json').read_text())
            public_release_key = text.strip() == key and fingerprint == metadata['signingFingerprint']
        except (ValueError, OSError, KeyError):
            pass
    findings = [{'file': name, 'rule': rule} for rule, pattern in PATTERNS.items()
                if pattern.search(checked) and not (rule == 'ssh_public_key' and public_release_key)]
    if name == 'release-signing.pub' and not public_release_key:
        findings.append({'file': name, 'rule': 'invalid_release_public_key'})
    for match in IPV4.finditer(text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if not address.is_loopback:
            findings.append({'file': name, 'rule': 'non_loopback_ipv4'})
            break
    if any(value in text for value in denied):
        findings.append({'file': name, 'rule': 'operator_private_value'})
    return findings


def build(destination, denied):
    files = {}
    findings = []
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if not allowed(relative):
            continue
        if path.is_symlink():
            findings.append({'file': relative.as_posix(), 'rule': 'symlink'})
        elif path.is_file():
            data = path.read_bytes()
            findings.extend(inspect(relative.as_posix(), data, denied))
            files[relative.as_posix()] = data
    if 'mobile-ui/frontend/dist/index.html' not in files:
        raise SystemExit('Build the frontend before packaging.')
    if findings:
        print(json.dumps({'status': 'blocked', 'findings': findings}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files['FILES.sha256.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A previously reviewed artifact must never be silently overwritten.
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            item = zipfile.ZipInfo('codex-mobile-console/' + name)
            mode = 0o755 if name.endswith(('.sh', '.command')) else 0o644
            item.external_attr = (0o100000 | mode) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise SystemExit('Archive integrity check failed.')
        for name in archive.namelist():
            relative = name.removeprefix('codex-mobile-console/')
            if relative != 'FILES.sha256.json' and not allowed(Path(relative)):
                raise SystemExit('Unexpected archive member.')
            if inspect(relative, archive.read(name), denied):
                raise SystemExit('Archive privacy recheck failed.')
    print(json.dumps({'status': 'passed', 'archive': destination.name,
                      'source_and_build_files': len(manifest), 'private_findings': 0,
                      'archive_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}, indent=2))


def load_denied(path):
    denied = json.loads(path.read_text()) if path else []
    if not isinstance(denied, list) or any(not isinstance(v, str) or len(v.strip()) < 4 for v in denied):
        raise ValueError('Private deny-list entries must contain at least four characters.')
    return denied


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--deny-file', type=Path, help='Private JSON list outside the release tree; never bundled or printed')
    args = parser.parse_args()
    denied = load_denied(args.deny_file)
    build(args.output.resolve(), denied)
