# KWin gesture cancellation integration

This patch targets **Fedora kwin-6.8.2-3.fc44** and the inspected
**libinput-1.31.3-1.fc44**. It adds the device-scoped D-Bus method
`org.kde.KWin.InputDevice.cancelTapGestures() -> bool` for the PalmReject
virtual touchpad only. It is not a general-purpose method for other devices.

The method drains preceding input, temporarily resets tapping through libinput,
restores its original value, and delivers queued button releases. These operations
run on the compositor thread under the input connection mutex. It does not call
KDE preference setters, emit preference-change signals, or write saved settings.
The D-Bus method uses a delayed reply instead of blocking the input thread while
waiting for the compositor thread, avoiding a shutdown deadlock.
The virtual device remains connected. It releases a drag at the current position;
it cannot undo clicks or actions already delivered to applications.

## Step-by-step guides

- [Build, test and install custom KWin](../../docs/custom-kwin-build-test-install.md):
  the pinned build, existing RPM shortcut, source verification, build/test commands,
  installation, desktop acceptance and stock rollback.
- [Update custom KWin](../../docs/custom-kwin-update.md): ordinary Fedora updates,
  preserving rollback packages, reviewing a new source base, rebasing the patch,
  updating the pinned recipe, rebuilding, installation and recovery.

The preparation script currently accepts only `kwin-6.8.2-3.fc44`. It does not
rebase the patch for another version. The convenience build wrapper always uses
`artifacts/kwin-build`; the update guide uses direct `rpmbuild` commands for new
version-specific build directories.

## Behavior and acceptance

The spec builds the libinput unit-test subtree and runs
`kwin-testLibinputDevice` under an isolated D-Bus with Qt's offscreen platform.
The downstream `KWIN_BUILD_PALMREJECT_TESTS_ONLY` CMake option avoids unrelated
integration-test dependencies without changing production compositor features.
Unit tests verify reset order, preserved preferences, identity checks and the
exported method's reply. They do not establish actual desktop tap/drag behavior.

Filtered trials require the patched interface before grabbing input. A missing
interface, failed helper or cancellation timeout ends the trial. Probe,
observation and passthrough remain available without the patched interface.

Session selection requires one active Wayland session for the selected UID and
its user bus. The logind `Desktop` field may be empty; the helper verifies KWin
and the cancellation API directly before the physical device is grabbed.

Normal tap-to-click stays enabled. Rejection releases tap-generated dragging,
including drag lock; releasing an item can drop it at its current position.
Previously completed actions cannot be undone. The filter keeps its global palm
lock until physical contacts and buttons release.

There is no automatic patch-rebase/rebuild service or permanent PalmReject boot
service in this checkout. A later stock KWin update can remove the interface;
filtered startup must then fail before grabbing input. Rebase and retest against
the new sources rather than indefinitely freezing desktop updates.

## Current installation status

The [2026-11-07 validation](../../docs/kwin-validation-2026-11-07.md) confirms
custom KWin is installed and running and exposes cancellation on the actual
virtual touchpad. Automated checks passed; full desktop acceptance remains
unfinished. See [troubleshooting](../../docs/troubleshooting.md) and
[rollback](../../docs/uninstall-rollback.md) for operational guidance.

## Validation record (build completed 2026-11-07)

- Original KWin and libinput source RPM signatures verified.
- KWin source SHA-256:
  `9f70a200139689b206b6d387433be4c346210b40e49d0a7f226b8ce674b6cfbb`.
- Inspected libinput source SHA-256:
  `3393d6ab25b91445d91fc89a4628ae5b869aaeaa1dc53e48e818164719e7f73c`.
- Fedora source preparation with the cancellation patch: passed without fuzz.
- Full KWin RPM build and its package test stage: passed.
- All 307 KWin device-test cases: passed, including the delayed D-Bus reply.
- Runtime RPM digests verified; dependencies, payload paths (apart from build-ID
  links), file capabilities and scriptlets match stock after release normalization.
- DNF transaction preview: only the three installed KWin runtime packages upgrade;
  no additional dependencies or downloads. Preview aborted without installation.
- Build log: `artifacts/kwin-build/build.log`; package hashes and validation summary:
  `artifacts/kwin-build/validation.json`; saved stock RPMs: `artifacts/kwin-stock`.
- At the end of the build, no custom KWin package had been installed by the build
  process. Subsequent installation/running-state evidence is linked above.
- Generated validation manifests are not automatically refreshed by rebuilding.
