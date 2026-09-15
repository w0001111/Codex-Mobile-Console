# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Build the pinned upstream source plus the reviewed console patch locally."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def run(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def build(archive_path=None):
    manifest = json.loads((ROOT / 'patches/cc-connect.json').read_text())
    patch = ROOT / 'patches/cc-connect.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patch_sha256']:
        raise SystemExit('cc-connect patch checksum mismatch.')
    go = os.environ.get('GO_BIN') or shutil.which('go')
    if not go or not shutil.which('git'):
        raise SystemExit('Install Go 1.25+ and Git first (or set GO_BIN).')
    # Build state is never part of the distributable source archive.
    cache = ROOT / '.build'
    cache.mkdir(mode=0o700, exist_ok=True)
    source_archive = Path(archive_path) if archive_path else cache / 'cc-connect-upstream.tar.gz'
    if not source_archive.exists():
        with urllib.request.urlopen(manifest['archive_url'], timeout=90) as response:
            temporary = source_archive.with_suffix('.download')
            try:
                with temporary.open('xb') as stream:
                    shutil.copyfileobj(response, stream)
                temporary.replace(source_archive)
            finally:
                temporary.unlink(missing_ok=True)
    if hashlib.sha256(source_archive.read_bytes()).hexdigest() != manifest['archive_sha256']:
        raise SystemExit('Upstream checksum mismatch; refuse to build. Remove the invalid .build archive before retrying.')
    with tempfile.TemporaryDirectory(prefix='cc-source-', dir=cache) as temp:
        work = Path(temp)
        with tarfile.open(source_archive) as archive:
            members = archive.getmembers()
            for item in members:
                relative = Path(item.name)
                if relative.is_absolute() or '..' in relative.parts or not (item.isfile() or item.isdir()):
                    raise SystemExit('Unsafe upstream archive member.')
            archive.extractall(work, members=members, filter='data')
        directories = [p for p in work.iterdir() if p.is_dir()]
        if len(directories) != 1:
            raise SystemExit('Unexpected upstream source layout.')
        source = directories[0]
        run(['git', 'apply', '--check', str(patch)], cwd=source)
        run(['git', 'apply', str(patch)], cwd=source)
        # This suite exercises adapter contracts without signing into any platform.
        test_env = dict(os.environ, CC_CONSOLE_ROOT=str(ROOT),
                        CC_CONSOLE_PYTHON=str(ROOT / '.venv/bin/python'))
        run([go, 'test', '-tags', 'no_web goolm', './core', './config', '-run',
             'TestConsole|TestArgv|TestCommandArgv|Test.*ListenHost', '-count=1'], cwd=source, env=test_env)
        binary = work / 'cc-connect'
        run([go, 'build', '-trimpath', '-buildvcs=false', '-tags', 'no_web goolm',
             '-ldflags', '-s -w -X main.version=' + manifest['adapter_version'] +
             ' -X main.commit=' + manifest['upstream_commit'], '-o', str(binary), './cmd/cc-connect'], cwd=source)
        destination = ROOT / 'bin'
        destination.mkdir(mode=0o700, exist_ok=True)
        os.replace(binary, destination / 'cc-connect')
        # Preserve installation references locally; never package downloaded source/config.
        references = cache / 'upstream-reference'
        references.mkdir(exist_ok=True)
        for name in ('README.md', 'README.zh-CN.md', 'config.example.toml'):
            shutil.copyfile(source / name, references / name)
        (destination / 'build.json').write_text(json.dumps({
            'adapter_version': manifest['adapter_version'],
            'upstream_commit': manifest['upstream_commit'],
            'binary_sha256': hashlib.sha256((destination / 'cc-connect').read_bytes()).hexdigest(),
        }, indent=2) + '\n')
    print('cc-connect adapter built at bin/cc-connect. Next: .venv/bin/python scripts/configure.py')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Optional already-downloaded pinned upstream archive')
    args = parser.parse_args()
    build(args.archive)
