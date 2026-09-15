#!/bin/sh
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
set -eu
umask 077
release_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$release_root/mobile-ui"
exec "$release_root/.venv/bin/python" server.py
