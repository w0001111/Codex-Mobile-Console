# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Installation-local paths; no developer machine paths or credentials."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get('MOBILE_STATE_DIR', str(ROOT / 'private'))).expanduser().resolve()
BRIDGE_STATE = STATE / 'bridge'
CODEX_HOME = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser().resolve()
