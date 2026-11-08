# Build and operate PalmReject

Use Bash in Konsole, from this checkout. `sudo` needs a real terminal for password
or fingerprint authentication. This guide covers the local program; custom KWin
has its own [installation](custom-kwin-build-test-install.md) and
[update](custom-kwin-update.md) guides. See [current status](../README.md#current-status)
and [troubleshooting](troubleshooting.md) before interpreting earlier records.

## Dependencies and local build

On Fedora, the dependencies are GCC, make, Linux input headers, libevdev,
libinput development files, and Python 3 with D-Bus bindings for filtering.
Permanent operation also needs Python GObject/GLib bindings and flock (util-linux).
The launcher also uses systemd, logind, runuser and ordinary core utilities.
If dependencies are missing, install them explicitly:

```sh
sudo dnf install gcc make kernel-headers libevdev-devel libinput-devel python3-dbus python3-gobject
```

Build as your ordinary user, without sudo:

```sh
make
make test
make analyze
```

The build prefers canonical libevdev headers. Without them it uses the small
public-ABI declaration header and links against `libevdev.so.2`; no private
libevdev implementation is included. Tests use synthetic input and do not grab
hardware. `make analyze` uses GCC's static analyzer.

`make sanitize` additionally needs working `libasan` and `libubsan`. It cleans
and rebuilds the local test/program binaries with instrumentation. To return to a
normal live-trial build afterward, run `make clean` followed by `make`. Do not run
these cleaning targets if you intend to retain the exact existing local binaries.

## Discover and calibrate without interception

```sh
sudo ./palmreject --probe
sudo ./palmreject --observe
```

Neither mode creates a virtual device or grabs input. Observation lasts 60 seconds;
`--duration` is for live modes only. Discovery requires one validated physical
match. Optional `--device /dev/input/by-id/...` must pass the same validation.
Printed `eventN` paths can change; do not treat them as stable identities.

Observe and label ordinary fingers, thumbs, edge motions, multiple fingers and
resting palms. Output includes position and size; keep recordings private unless
needed. No keyboard events are collected. The driver's `touch` value is derived
from proximity, not generic physical pressure.

Create a personal profile once; do not overwrite an existing calibration:

```sh
cp -n config/profile.example config/my-profile.conf
```

Edit every placeholder using the labeled measurements:

| Field | Meaning and bounds |
| --- | --- |
| `width_threshold` | Global raw width, 1–65535. |
| `touch_threshold` | Global raw proximity, 1–65535. |
| `edge_width_threshold` | Raw width at left/right edges, 1–65535 and no greater than global width. |
| `edge_percent` | Each side's fraction of measured X span, 1–25 percent. |

Comparisons are strictly greater-than; there are no default thresholds. Unknown,
duplicate, missing, out-of-range and shell-expression values are rejected.
Profiles are parsed as data, never sourced or evaluated. The template is
intentionally invalid until edited. Personal files under `config/` are ignored;
`config/profile.example` remains trackable.

Check the predictions while physical input continues normally:

```sh
sudo ./palmreject --observe --config "$PWD/config/my-profile.conf"
```

`palm=1` means the frame contains a palm candidate; `palm=-1` means no profile
was supplied. Correct calibration before filtering if ordinary fingers trigger
rejection or labeled palms do not. A positive classification locks all contacts,
not just the large contact.

## Manual launch and duration

Connect and test a USB mouse and keyboard, save work, and keep another terminal
ready to stop the trial. Stop `palmreject.service` if installed; the launchers
share a lifecycle lock. Stop any older upstream filter separately; never run two
filters on the same device. Lift all contacts and release buttons during handover.
First check access under the service restrictions:

```sh
sudo scripts/trial.sh --probe
```

Then test forwarding, without classification:

```sh
sudo scripts/trial.sh --passthrough --recovery-ready
```

`--recovery-ready` acknowledges tested independent recovery devices. Check pointer
motion, physical clicks, taps, dragging, scrolling, pinch and KDE gestures. Verify
manual stop and automatic expiry in separate trials before filtering:

```sh
sudo scripts/trial.sh --filter --config "$PWD/config/my-profile.conf" --recovery-ready
```

Filtering requires the patched KWin interface and exactly one active Wayland
session for the selected nonroot UID, plus its user bus. Normally `sudo` provides
`SUDO_UID`; `--session-uid UID` explicitly selects the desktop user when needed.
An empty logind `Desktop` field is allowed; the helper checks KWin itself.
`--device PATH` is an optional validated physical-device override. `--state-dir`
is an internal program option managed by the launcher, not a setup step.

The default live limit is **60 seconds**, independently enforced by the process
and systemd. For one hour:

```sh
sudo scripts/trial.sh --filter --config "$PWD/config/my-profile.conf" --recovery-ready --duration 3600
```

`--duration` accepts integers 1–86400 (24 hours), without leading zeroes, for
passthrough/filter only. It does not install or enable a boot service.

The launcher copies the executable/profile into a root-owned temporary directory,
validates the trackpad, and creates `palmreject-trial.service`. It permits only
uinput, the selected physical device and the verified new virtual event node.
On SELinux systems it labels only the disposable executable `bin_t`; it does not
change enforcement or policy. Virtual touchpad recognition must succeed within
10 seconds before grabbing input. Filtering also authenticates the session helper
and checks cancellation readiness. A contact appearing during handover aborts.

The virtual touchpad can have its own KDE settings. Select **PalmReject
MacBookPro16,1 Touchpad**, compare against your baseline, and keep tapping enabled.
Test rejection during a tap, tap-and-drag, and drag lock after fingers lift using
a disposable drag target. Verify no extra click, released drag, normal input
following physical release, and unchanged preferences/device connection. Follow
all [remaining desktop acceptance checks](kwin-validation-2026-11-07.md#hands-on-checks-still-required).

## Stop and read logs

Ctrl+C in the launcher terminal stops the service. From another terminal:

```sh
sudo systemctl stop palmreject-trial.service
```

The launcher normally cleans up its runtime directory and temporary unit
properties on exit. It uses no automatic restart; it is ordered to stop before
sleep/T2 suspend actions and stays stopped after wake. A missing unit after cleanup
is normal. Stopping restores physical input independently of uninstalling KWin.

Inspect status/logs without launching a trial:

```sh
systemctl status palmreject-trial.service --no-pager
journalctl -u palmreject-trial.service -n 80 --no-pager
journalctl -u palmreject-trial.service -f
```

`journalctl -f` follows logs only; Ctrl+C there stops the log viewer. It does not
stop PalmReject. The launcher also prints logs when the trial finishes.

See [rollback](uninstall-rollback.md) for leftovers after a forcibly killed launcher.
Permanent operation uses the separate service described below.

## Permanent installation

Build/test normally, calibrate, install matching custom KWin, and verify short
trials and USB recovery devices first. The installer copies reviewed local output;
it never builds as root, installs dependencies or installs custom KWin for you.
Lift all contacts/buttons during handover. From the desktop user's terminal:

```sh
sudo ./install.sh --dry-run --config "$PWD/config/my-profile.conf"
sudo ./install.sh --config "$PWD/config/my-profile.conf"
```

`--session-uid UID` overrides the nonroot UID from `SUDO_UID`.
`--stock-rpm-dir DIR` selects saved, signed stock KWin RPMs; the default is
`artifacts/kwin-stock`. All installed KWin subpackages need exact matching stock
RPMs for rollback, including development/documentation packages if installed.
Installation fails on a missing signature, mismatched desktop base or unrelated
existing installation files/units. Dry-run validates inputs and prints actions;
it makes no file/service/package changes.

The installer records hashes/backups under `/var/lib/palmreject/`, saves verified
root-owned stock RPMs there, installs executables in `/usr/local/libexec/palmreject/`,
and copies the profile/settings into `/etc/palmreject/`. These copies are independent
of the checkout. Source profile values are neither printed nor shell-evaluated.
The completed install stops an existing recognized trial, waits for its cleanup,
and enables/starts `palmreject.service`.

The supervisor starts at boot and waits for exactly one active Wayland session
for the configured user and its KWin bus owner. Session readiness gets 60 seconds;
worker/cancellation startup gets 30 seconds, retaining the shorter internal device
and cancellation deadlines. It creates `palmreject-input.service` with narrow device
access and runs the helper as the desktop user. `--persistent` is an internal
filter option: it removes trial expiry, not validation or cancellation checks.
`--check-config FILE` validates a profile offline without accessing devices.

Runtime failure stops the worker/helper and latches that login; there are no
repeated grabs. A new login or explicit supervisor restart permits another attempt.
Switching away from the active session also releases input; returning to an already
attempted session requires a manual restart. Locking the same active session does
not itself restart filtering.

Before suspend the supervisor releases input using logind's delay inhibitor and
worker ordering before T2 suspend services. After wake it waits for those services
to finish successfully, rediscovers input and restarts only if filtering was healthy
before sleep. Manual stops and failure latches survive sleep. Logout stops input.
The supervisor's own stop/crash stops its bound worker; recognized transient
leftovers can be recovered on supervisor restart.

```sh
systemctl status palmreject.service palmreject-input.service --no-pager
journalctl -u palmreject.service -u palmreject-input.service -n 100 --no-pager
sudo systemctl stop palmreject.service
sudo systemctl restart palmreject.service
sudo systemctl disable --now palmreject.service
```

`stop` leaves filtering stopped until explicitly started or the next boot; it does
not return at the next login while the supervisor is stopped. `restart` clears the
failure latch. `disable --now` also removes boot activation. To enable again:

```sh
sudo systemctl enable --now palmreject.service
```

The supervisor may be active while waiting or after a worker failure. Read its
status text and worker journal; an active supervisor alone is not proof of filtering
or hands-on acceptance. [Uninstall/rollback](uninstall-rollback.md) covers removal.

## Update the local program

Inspect `git status --short` and preserve local changes/profile before bringing
in reviewed source changes. No automatic pull/reset or package update is required.
After updating the source, as your ordinary user:

```sh
make
make test
make analyze
```

A running trial uses its disposable executable/profile copies; rebuilding this
checkout does not update that instance. Stop it explicitly when ready, then launch
a new short supervised trial with the measured profile. Do not overwrite sources
or profiles to recover from a failed build. Recheck calibration if classifier or
driver semantics change. KWin/libinput updates require their separate review and
[custom KWin update procedure](custom-kwin-update.md).

For an installed service, rerun the installer with the reviewed build/profile and
matching stock RPMs to upgrade the root-owned copies. Rebuilding the checkout or
editing its profile alone does not update the installation. Unexpectedly modified
installed files are preserved and must be inspected before reinstalling; backups
and manifest records remain available. After a KWin base update, refresh the saved
rollback set through installation before relying on the uninstaller's package
rollback. No automatic source update, patch rebase or RPM rebuild is performed.
