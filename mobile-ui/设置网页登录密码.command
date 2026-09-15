#!/bin/zsh
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
set -eu
cd "${0:A:h}"
../.venv/bin/python local_admin.py set-password
printf '\n按回车关闭此窗口。'
read -r reply
