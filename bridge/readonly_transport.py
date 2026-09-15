# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Bounded app-server transport for read-only catalog and history queries."""
import collections
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import tomllib

def disabled_mcp_args(names):
    args = []
    for name in names:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise RuntimeError('Unsupported MCP configuration name')
        args += ['-c', f'mcp_servers.{name}.enabled=false']
    return args

class Server:

    def __init__(self, cwd, overrides=None):
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        config_path = home / 'config.toml'
        config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
        binary = os.environ.get('CONTROL_CODEX_BINARY') or shutil.which('codex')
        if not binary:
            raise RuntimeError('codex binary not found')
        args = [binary, 'app-server', '--listen', 'stdio://', '-c', 'web_search="disabled"']
        args += disabled_mcp_args(config.get('mcp_servers', {}))
        for (key, value) in (overrides or {}).items():
            if not re.fullmatch('[A-Za-z0-9_.-]+', key) or not isinstance(value, (str, bool, int)):
                raise ValueError('Invalid local server override')
            args += ['-c', key + '=' + json.dumps(value)]
        self.process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.queue = queue.Queue()
        self.pending = collections.deque()
        self.serial = 0
        self.deadline = time.monotonic() + 180
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.process.stdout:
            try:
                self.queue.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        self.queue.put(None)

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def receive(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Probe server deadline exceeded')
        try:
            value = self.queue.get(timeout=min(remaining, 120))
        except queue.Empty:
            raise TimeoutError('No app-server response within timeout') from None
        if value is None:
            raise RuntimeError('App-server closed its output')
        if 'method' in value and 'id' in value:
            self.send({'id': value['id'], 'error': {'code': -32601, 'message': 'Probe does not permit tools or approvals'}})
            raise RuntimeError('Unexpected server request; probe halted')
        return value

    def request(self, method, params):
        self.serial += 1
        request_id = self.serial
        self.send({'id': request_id, 'method': method, 'params': params})
        while True:
            value = self.receive()
            if value.get('id') == request_id:
                if 'error' in value:
                    raise RuntimeError(f"{method} failed: code {value['error'].get('code')}")
                return value['result']
            self.pending.append(value)

    def initialize(self):
        self.request('initialize', {'clientInfo': {'name': 'mobile-console-reader', 'version': '0.1.0'}, 'capabilities': {'experimentalApi': True}})
        self.send({'method': 'initialized'})

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        self.process.stdout.close()
