# Build, test and install custom KWin

This guide is for this Fedora 44 / KDE Wayland checkout and the PalmReject
cancellation patch. Commands use Bash in **Konsole**, not the chat's shell-command
shortcut: `sudo` needs a real terminal for password or fingerprint authentication.

The reviewed base is **kwin-6.8.2-3.fc44**. The custom packages are
**6.8.2-3.palmreject1.fc44**. For a different KWin version, use the
[update guide](custom-kwin-update.md) first. Do not install this older build over a
newer desktop.

The current checkout already contains built RPMs and passing test records. To use
those files, do steps **1–2**, then continue at **7**. Steps **3–6** explain how to
reproduce the build.

## 1. Open the checkout and check the installed version

```sh
cd "$HOME/Documents/T2-PalmReject"
rpm -q kwin kwin-common kwin-libs
rpm -q kwin-devel kwin-doc
```

The three runtime packages must belong to the same release. For this guide,
expect the stock `6.8.2-3.fc44` release, or the custom release above if you have
already installed it. A “not installed” result for `kwin-devel` or `kwin-doc` is
normal on this machine.

If development or documentation subpackages are installed, their matching custom
RPMs must be included in the installation and rollback transactions too. The
three-package commands below assume neither is installed.

## 2. Prepare recovery and save the stock packages

Connect and test a separate USB mouse and keyboard. Save your work before changing
the desktop packages. Keep this stop command available in another terminal:

```sh
sudo systemctl stop palmreject.service
sudo systemctl stop palmreject-trial.service
```

If no trial unit exists, a “unit not loaded” message is expected.

Download the matching stock packages for offline rollback:

```sh
mkdir -p artifacts/kwin-stock
dnf download --arch=x86_64 --destdir=artifacts/kwin-stock \
  kwin-6.8.2-3.fc44 kwin-common-6.8.2-3.fc44 kwin-libs-6.8.2-3.fc44
rpm --checksig artifacts/kwin-stock/kwin{,-common,-libs}-6.8.2-3.fc44.x86_64.rpm
```

The signatures and digests must verify. If a package is missing from the
repositories or verification fails, resolve that before installing custom KWin.
The stock packages saved during this development session are already in this
directory.

If `dnf download` is unavailable, install the packaging tools from step 3, then
repeat this step.

## 3. Install build tools and download the exact source

```sh
sudo dnf install rpm-build dnf5-plugins gcc gcc-c++ make
mkdir -p artifacts/kwin
dnf download --srpm --destdir=artifacts/kwin kwin-6.8.2-3.fc44
rpm --checksig artifacts/kwin/kwin-6.8.2-3.fc44.src.rpm
```

The preparation script also checks the source RPM's signature and this pinned
SHA-256:

```text
9f70a200139689b206b6d387433be4c346210b40e49d0a7f226b8ce674b6cfbb
```

A different source RPM is not an interchangeable replacement. Follow the update
guide if the pinned version is no longer the version you want to build.

## 4. Prepare a clean build tree

The helper expects `artifacts/kwin-build` to be a **new directory**. If it already
exists and you want a complete rebuild, first archive it:

```sh
mv -- artifacts/kwin-build "artifacts/kwin-build-backup-$(date +%Y%m%d-%H%M%S)"
```

Run that command only when the directory exists and no build is running. It
preserves the old RPMs and logs. Do not delete your only rollback copy.

Prepare the new tree as your ordinary user:

```sh
python3 packaging/kwin/prepare.py \
  artifacts/kwin/kwin-6.8.2-3.fc44.src.rpm artifacts/kwin-build
```

Success creates a patched spec, source files, and a custom source RPM under
`artifacts/kwin-build`. A source RPM is build input; it is not the desktop package
you install.

If preparation rejects the hash, release field, or directory, stop and investigate
the stated reason. Do not bypass the version check to build another release.

## 5. Install development dependencies and build

```sh
sudo dnf builddep "$PWD/artifacts/kwin-build/SPECS/kwin.spec"
```

Then build **without sudo**:

```sh
set -o pipefail
bash scripts/build-kwin.sh 2>&1 | tee artifacts/kwin-build/build.log
```

The wrapper uses four build jobs. This is a full desktop compositor build and can
take a substantial amount of time. It prepares the source again, compiles KWin,
stages files in a build directory, runs tests, and writes RPMs. Its `%install`
stage does not install anything into the running system.

The pipeline must finish successfully. `pipefail` prevents `tee` from hiding a
failed build. If it fails, inspect the log and fix the failure before continuing.
Re-running the wrapper starts source preparation again; it is not a resume command.

## 6. Check the build and test results

The spec enables the libinput unit tests and runs `kwin-testLibinputDevice` on an
isolated D-Bus with Qt's offscreen platform. It does not use your running KWin or
grab physical input. Missing tests fail the package build.

Inspect the result:

```sh
rg 'Test #|tests passed|FAIL!|Wrote:' artifacts/kwin-build/build.log
ls artifacts/kwin-build/RPMS/x86_64
```

Look for `kwin-testLibinputDevice ... Passed` and
`100% tests passed, 0 tests failed out of 1`. The one CTest entry runs the whole
device-test program, not just one internal test case.

RPM can remove the temporary `BUILD/` tree after a successful build. That also
removes CTest's `Testing/Temporary/LastTest.log`; its absence is expected after
cleanup. Use the persistent `artifacts/kwin-build/build.log` captured in step 5.
You do not need to rebuild merely to recover that temporary file.

The earlier detailed test run inspected during development reported **307 passing
device-test cases**, including reset behavior and the exported D-Bus reply.
CTest's `--output-on-failure` does not print all passing cases into the build log.
This is unit-test evidence; desktop gesture testing is still a separate step.

The three runtime RPMs are:

```text
kwin-6.8.2-3.palmreject1.fc44.x86_64.rpm
kwin-common-6.8.2-3.palmreject1.fc44.x86_64.rpm
kwin-libs-6.8.2-3.palmreject1.fc44.x86_64.rpm
```

You do not need the generated debug or development packages unless you already
use those subpackages.

## 7. Verify and preview the installation

```sh
rpm --checksig artifacts/kwin-build/RPMS/x86_64/kwin{,-common,-libs}-6.8.2-3.palmreject1.fc44.x86_64.rpm
dnf --assumeno install artifacts/kwin-build/RPMS/x86_64/kwin{,-common,-libs}-6.8.2-3.palmreject1.fc44.x86_64.rpm
```

Locally built RPMs have verified digests but are not signed with Fedora's signing
key. The downloaded stock/source RPMs must have valid Fedora signatures. Do not
disable system-wide signature checks to handle an installation error.

`--assumeno` previews the transaction and deliberately aborts it; a nonzero exit
for that abort is expected. With the stock version used here, it should upgrade
only `kwin`, `kwin-common`, and `kwin-libs`. If the custom version is already
installed, “nothing to do” is also expected. Investigate unexpected removals or
version changes before proceeding.

If present, `artifacts/kwin-build/validation.json` records hashes and checks for
the original development build. It is not generated automatically by the build
wrapper. A later rebuild needs its own validation record; do not treat an old JSON
file as evidence for newly overwritten RPMs.

## 8. Install the runtime packages together

Save your work, then run:

```sh
sudo dnf install artifacts/kwin-build/RPMS/x86_64/kwin{,-common,-libs}-6.8.2-3.palmreject1.fc44.x86_64.rpm
rpm -q kwin kwin-common kwin-libs
```

All three should now report `6.8.2-3.palmreject1.fc44`.

**Log out and log back in normally.** Installing files does not replace the KWin
process already running in your session. Do not kill or replace that process in
place.

## 9. Build PalmReject and check access after logging in

Open Konsole again:

```sh
cd "$HOME/Documents/T2-PalmReject"
sudo dnf install gcc make kernel-headers libevdev-devel libinput-devel python3-dbus
make
make test
make analyze
sudo scripts/trial.sh --probe
```

These checks should pass before a live trial. The service probe reads device
metadata without grabbing the trackpad or creating a virtual device.

If you separately run `make sanitize`, rebuild normally afterward using
`make clean` followed by `make`. Do not use an instrumented binary for the live
trial.

## 10. Test passthrough, then filtering

Use the tested USB recovery devices and keep the stop command from step 2 ready.
First run:

```sh
sudo scripts/trial.sh --passthrough --recovery-ready
```

Check pointing, ordinary clicks, taps, dragging, scrolling, pinch and your KDE
gestures. Verify both manual stopping and automatic expiry, using separate trials.
The physical trackpad must work again afterward; lift all contacts when checking
handover.

Then use your measured profile:

```sh
sudo scripts/trial.sh --filter --config "$PWD/config/my-profile.conf" --recovery-ready
```

`--recovery-ready` acknowledges that you have tested the separate mouse and
keyboard. `config/my-profile.conf` must contain measured values, not the unedited
template. Observation/calibration instructions are in the [PalmReject guide](palmreject.md#discover-and-calibrate-without-interception).

For filtered testing, select **PalmReject MacBookPro16,1 Touchpad** in KDE's
touchpad settings and keep tap-to-click enabled. Use a harmless test window and a
disposable item for dragging. Repeat the following across as many 60-second
trials as necessary:

| Test | Expected result |
| --- | --- |
| Normal one-, two-, and three-finger taps and double taps | Your configured actions still work. |
| Brief stationary contact becomes palm-sized | Rejection causes no new tap-click. |
| Palm arrives while another finger lifts | No extra tap-click appears. |
| Palm appears during tap-and-drag | The held button releases; the item may drop at its current position. |
| Same test with drag lock enabled | The drag ends instead of remaining held. |
| Drag lock holds after all fingers lift, then a palm arrives | The held button releases even though no old contact remains. |
| All physical contacts/buttons release after rejection | Normal pointing and tapping resume. |
| Repeated rejection cycles | The virtual device stays connected and KDE settings stay unchanged. |

Cancellation cannot undo a click or drop already delivered to an application.
This filter still blocks the whole virtual trackpad while a palm lock is active.

After the short checks succeed, a longer manual session can use `--duration 3600`
for one hour (maximum `86400`, or 24 hours). Add it to the filtered trial command
above. Both automatic-stop limits use that duration; Ctrl+C or the stop command
still ends it early. No boot activation is added.

For logs:

```sh
journalctl -u palmreject-trial.service -n 80 --no-pager
```

If cancellation is unavailable, filtering should abort before grabbing input.
Check that you logged in after installing the custom package. Other failures need
investigation before permanent startup. Crash/output-failure and suspend tests
are listed in the [hardware acceptance plan](history/fedora-macbookpro16-1-plan.md).

## 11. Restore stock KWin if necessary

Stop the trial, then downgrade all three runtime packages together:

```sh
cd "$HOME/Documents/T2-PalmReject"
sudo systemctl stop palmreject.service
sudo systemctl stop palmreject-trial.service
sudo dnf downgrade artifacts/kwin-stock/kwin{,-common,-libs}-6.8.2-3.fc44.x86_64.rpm
```

Log out and back in normally. If the graphical session cannot start, use the USB
keyboard to open a text console with `Ctrl+Alt+F3` (possibly also `Fn`), log in,
and run the same rollback command. Reboot afterward if you cannot return to a
working graphical session.

An absent trial-unit error does not prevent the downgrade. If you have since
updated the desktop to a different upstream version, use its matching stock RPMs
and the [update guide](custom-kwin-update.md), rather than blindly downgrading to
6.8.2.

This procedure installs custom KWin only. After supervised acceptance, follow the
[permanent PalmReject installation](palmreject.md#permanent-installation) separately.
