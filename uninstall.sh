#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -eu
cat <<'MESSAGE'
This compatibility script does not stop services or remove files/packages.
Read docs/uninstall-rollback.md to stop PalmReject, remove local files or restore
stock KWin. Preserve calibration profiles and rollback RPMs unless you choose
otherwise. Custom KWin package instructions: docs/custom-kwin-build-test-install.md.
Older upstream installations need their original removal procedure.
MESSAGE
