#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -eu
cat <<'MESSAGE'
Automatic PalmReject installation is disabled in this experimental adaptation.
For local build, calibration and manual launch, read docs/palmreject.md.
For custom KWin installation, read docs/custom-kwin-build-test-install.md.
For stopping/removal and stock KWin recovery, read docs/uninstall-rollback.md.
No files, packages, services or boot settings are changed by this script.
MESSAGE
[[ "${1:-}" == --help || "${1:-}" == --dry-run ]] && exit 0
exit 1
