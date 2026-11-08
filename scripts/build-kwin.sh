#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="$root_dir/artifacts/kwin-build"
(( EUID != 0 )) || { echo 'Build KWin as your ordinary user, without sudo.' >&2; exit 1; }
jobs="${PALMREJECT_BUILD_JOBS:-4}"
[[ "$jobs" =~ ^([1-9]|[12][0-9]|3[0-2])$ ]] || { echo 'PALMREJECT_BUILD_JOBS must be 1–32.' >&2; exit 2; }
[[ -f "$build_dir/SPECS/kwin.spec" ]] || {
    echo 'Prepare the source package first; see packaging/kwin/README.md.' >&2; exit 1;
}
cmp -- "$root_dir/packaging/kwin/0001-palmreject-cancel-tap-gestures.patch" \
    "$build_dir/SOURCES/0001-palmreject-cancel-tap-gestures.patch" || {
    echo 'The prepared KWin patch is stale; prepare a fresh build tree.' >&2; exit 1;
}
exec rpmbuild -ba --define "_topdir $build_dir" --define "_tmppath $build_dir" \
    --define "_smp_build_ncpus $jobs" "$build_dir/SPECS/kwin.spec"
