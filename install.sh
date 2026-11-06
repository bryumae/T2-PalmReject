#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -eu
cat <<'MESSAGE'
Automatic installation is disabled in this experimental Fedora adaptation.
Build with make as your ordinary user. Read README.md, then use scripts/trial.sh
for a supervised 60-second test. No boot service or sleep hook is installed.
MESSAGE
[[ "${1:-}" == --help || "${1:-}" == --dry-run ]] && exit 0
exit 1
