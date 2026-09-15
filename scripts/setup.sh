#!/bin/sh
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
set -eu
umask 077
release_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$release_root"
python_bin=${PYTHON_BIN:-python3}
"$python_bin" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required; set PYTHON_BIN"'
"$python_bin" -m venv .venv
.venv/bin/python -m pip install -r mobile-ui/requirements.lock
npm --prefix mobile-ui/frontend ci --ignore-scripts
npm --prefix mobile-ui/frontend run build
.venv/bin/python scripts/build_cc_connect.py
printf '%s\n' 'Dependencies and frontend are ready. Follow README.md to configure your own identity and HTTPS.'
