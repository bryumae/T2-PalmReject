#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --help ]]; then
    echo 'Usage: detect-trackpad.sh (requires a built palmreject and device read access)'
    exit 0
fi
(( $# == 0 )) || exit 2
probe="$("$root_dir/palmreject" --probe)"
IFS=' ' read -r field _ <<< "$probe"
printf '%s\n' "${field#device=}"
