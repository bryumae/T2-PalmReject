# Troubleshoot PalmReject and custom KWin

Use Bash in Konsole from the checkout. These are diagnostic recipes for a later
session; documentation cleanup does not run live trials or change packages.
Keep tested USB recovery devices available for live testing. For current evidence
and open findings, see the [dated validation](kwin-validation-2026-11-07.md).

## Establish which component failed

```sh
./palmreject --help
bash scripts/trial.sh --help
systemctl status palmreject.service palmreject-input.service palmreject-trial.service --no-pager
journalctl -u palmreject-trial.service -n 100 --no-pager
rpm -q kwin kwin-common kwin-libs libinput
```

A missing transient unit after launcher cleanup is normal; journal records may
still exist. Status success means the process ran/exited, not that desktop
acceptance passed. `journalctl` only reads logs. Use the
[PalmReject guide](palmreject.md#manual-launch-and-duration) to launch it.

## Permanent supervisor is active but filtering is not

```sh
systemctl status palmreject.service palmreject-input.service --no-pager
journalctl -u palmreject.service -u palmreject-input.service -n 100 --no-pager
```

The supervisor can be waiting for the configured session, paused for sleep/T2
resume, or holding a failure latch. Read its status text, not just `active`.
A missing worker while waiting is expected. Missing KWin integration, non-idle
handover, helper failure or timeout leaves physical input available and does not
loop retries. After fixing the cause, use `sudo systemctl restart palmreject.service`.
A new login also permits a new attempt if the supervisor itself remains running.

Stop the supervisor before running trials; both launchers share a lifecycle lock.
Manual supervisor stops do not automatically resume after sleep. If T2 resume
services fail or remain active, filtering waits rather than racing the driver.
Rebuilding/editing the checkout does not update installed copies: rerun the
[installer](palmreject.md#permanent-installation). Inspect unexpected file changes
before an upgrade; do not bypass ownership/manifest checks.

## Sudo fails or the program is missing

Run privileged commands in a real Konsole terminal, not the chat shell shortcut.
If authentication fails, resolve the terminal/password/fingerprint issue first.
For `Run make as the ordinary user first` or a missing `palmreject`, build with
`make` without sudo. Missing headers/libraries or Python D-Bus bindings need the
[documented dependencies](palmreject.md#dependencies-and-local-build).
Do not rebuild as root to work around a dependency failure.

## Device discovery fails or service access is denied

```sh
sudo ./palmreject --probe
sudo scripts/trial.sh --probe
```

The first checks identity/capabilities directly; the second checks access under
service restrictions. An ambiguous match or wrong driver/model needs investigation,
not a hardcoded `event8`. A stable `--device PATH` override still undergoes full
validation. Keyboards, force-click devices and virtual inputs are rejected.

Earlier startup failures involved the disposable executable's SELinux context and
the virtual node's device allowlist. The current launcher labels only its copy
`bin_t` when SELinux is enabled, then verifies/adds only the newly created virtual
node to the runtime allowlist. Use this launcher rather than an old copy or direct
live-mode invocation. If denials persist, inspect diagnostics:

```sh
getenforce
sudo journalctl -b --no-pager -g 'avc:|SELinux|palmreject'
```

Do not disable enforcement or grant broad input access. `Virtual event node
unavailable` or `Libinput did not recognize announced virtual node` requires
checking udev/libinput recognition and launcher allowlist setup. Lift all contacts
and buttons at startup; contact during handover aborts the trial. A failed readiness
check should leave original input available.

## Existing trial unit prevents startup

The launcher deliberately refuses existing units or drop-ins. Inspect them using
[the rollback guide](uninstall-rollback.md#stop-palmreject-only). If it is a running
trial, use that launcher's terminal or the documented stop command when you intend
to end it. If it is a leftover, establish ownership and exact paths before cleanup.
Never start a second filter alongside the first.

## Filtering reports no session, missing D-Bus or missing cancellation API

```sh
loginctl list-sessions
loginctl show-user "$UID" -p Sessions
printf '%s\n' "$XDG_SESSION_TYPE" "$XDG_RUNTIME_DIR" "$DBUS_SESSION_BUS_ADDRESS"
python3 -c 'import dbus'
rpm -q kwin kwin-common kwin-libs
```

Run the launcher through sudo from the desktop user's terminal. Filtering requires
one active Wayland session for its nonroot UID and `/run/user/UID/bus`. If needed,
pass `--session-uid` with that user's numeric UID. An empty logind `Desktop` field
was an earlier startup problem; the current launcher accepts it and the helper
validates the actual KWin owner/interface instead. Check per-session metadata with
`loginctl show-session SESSION_ID` using an ID from `list-sessions`.

`KWin lacks cancelTapGestures` or `KWin gesture cancellation unavailable` usually
means stock/old KWin is running or device identity/API checks failed. Confirm all
runtime packages match. Installing custom RPMs does not replace the running
compositor: log out/in normally when ready. A later stock update can remove the
API; follow the [KWin update guide](custom-kwin-update.md). Do not bypass this gate
or replace the running compositor in place. Probe/observe/passthrough do not need
the cancellation API.

## Cancellation timeout or helper failure ends a trial

The helper calls KWin with a 75 ms D-Bus timeout; the C protocol also bounds its
wait for acknowledgment. A timeout is a failed cancellation, not permission to
continue suppressing contacts. Read the trial journal and session KWin logs:

```sh
journalctl --user -b -u plasma-kwin_wayland.service -n 100 --no-pager
```

Record the action/time, helper exception, package versions and trial result.
Investigate compositor responsiveness, helper exit, user-bus availability and
matching integration before retrying a short supervised trial. Do not increase
limits or bypass acknowledgment to hide the failure. Lift contacts/buttons and
verify physical recovery. Cancellation cannot reverse an already delivered drop.

## Normal fingers are rejected, palms pass, or input stays locked

Use read-only observation with your profile:

```sh
sudo ./palmreject --observe --config "$PWD/config/my-profile.conf"
```

The example placeholders are intentionally invalid. Unknown/duplicate keys or
invalid bounds produce `Invalid profile`. Recalibrate against labeled samples;
`touch` is proximity-derived. Check edge thresholds and strict greater-than
comparisons. See [calibration](palmreject.md#discover-and-calibrate-without-interception).
A detected palm locks the whole trackpad until all physical contacts and buttons
release. Lift everything before judging recovery. Rebuilding/editing the profile
does not update a trial's disposable copy; a new launch uses the edited file.

## Taps or drag lock behave incorrectly

Select **PalmReject MacBookPro16,1 Touchpad** in KDE settings and check that tapping
and tap-and-drag match your intended settings. Test active dragging and drag lock
with no fingers down using disposable targets. Rejection should release held tap
buttons and keep preferences/device connection intact. The separate force-click
keyboard is outside this cancellation path. Collect a labeled reproduction and
logs if a click/drag remains stuck; stop the trial and verify physical recovery.
Use the [acceptance table](custom-kwin-build-test-install.md#10-test-passthrough-then-filtering)
to distinguish expected release/drop behavior from an extra click.

## Touch jumps or duplicate tracking-ID warnings

The validation found touch jumps on both physical and virtual inputs, including
physical jumps before custom KWin. Duplicate tracking-ID `-1` warnings were also
seen. Driver event stream and grab handover are hypotheses, not established causes.
If symptoms occur, compare labeled ordinary physical use, passthrough and filtering
in separate supervised sessions, noting times and actions. Avoid publishing raw
input logs unnecessarily. Do not attribute all warnings to the patch or dismiss
them solely because they predate it.

## Rendering warnings, flicker or screen sharing problems

```sh
journalctl --user -b -u plasma-kwin_wayland.service --no-pager -g 'swapchain|graphics buffer|mask|fail|error'
journalctl -b -k --no-pager -g 'amdgpu|i915|drm|suspend'
```

Real-session graphics-buffer allocation and unsupported-window-mask warnings
remain unexplained. Isolated animated rendering passed, but does not prove these
warnings harmless. AMD resets near resume also do not by themselves establish a
compositor crash; the validated active renderer was Intel. Record a reproducible
UI action, visible symptom and timestamp. Test actual screen sharing/display
workflows: portal service availability alone is not acceptance. A controlled
stock/custom comparison requires planned logout/package changes using the
[rollback guide](uninstall-rollback.md#restore-stock-kwin), not an in-place KWin restart.

## KWin test logs disappear or archived CTest cannot find executables

RPM may remove `BUILD/` after packaging; use the retained `build.log`. Archived
CTest files can reference the original absolute build path. Inspect those paths
and run the actual archived binaries in an isolated test environment as recorded
in the [validation report](kwin-validation-2026-11-07.md); this is distinct from a
code-test failure. Do not rebuild only to recover a removed temporary log.
`validation.json` is not refreshed automatically: verify new RPM hashes/results
rather than applying an old manifest to a rebuild.
