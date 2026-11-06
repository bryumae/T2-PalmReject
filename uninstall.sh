#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -eu
cat <<'MESSAGE'
This adaptation has no persistent installer. Stop a trial with:
  sudo systemctl stop palmreject-trial.service
The launcher cleans up its runtime artifacts when it exits.
An older upstream installation needs its original removal procedure; this script
will not delete or replace existing system files.
MESSAGE
