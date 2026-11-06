# T2 PalmReject — Fedora MacBookPro16,1 adaptation

Experimental userspace palm rejection for **MacBookPro16,1 / Apple 05ac:0340**,
Fedora 44, KDE Wayland, and the `t2_precision_trackpad` driver. Based on
[r2car/T2-PalmReject](https://github.com/r2car/T2-PalmReject), pinned at
`75b31901cf9e4c1e9336c51fc61347d988af5fe4`.

**Not hardware-validated yet.** Offline checks pass, but calibration, KDE gestures,
service isolation, suspend behavior and physical-input recovery must be tested on
the host. Filtering intentionally requires a calibration file. The Arch/MacBook
Air thresholds are not defaults for this driver.

The project reads only a validated physical trackpad, creates a virtual touchpad,
and grabs the physical device during a supervised trial. Stopping the process
releases the grab. A failed virtual output causes immediate physical-input release.
A detected palm suppresses all virtual contacts and clicking until contacts and
buttons are released. Simultaneous pointing with a resting palm is not supported.

## Build and offline verification

Build as your normal user, **without sudo**:

```sh
make
make test
make analyze
```

Dependencies: GCC, make, Linux input headers, libevdev runtime (`libevdev.so.2`),
and libinput development files. On Fedora, packages are `gcc`, `make`,
`kernel-headers`, `libevdev`, and `libinput-devel`. Prefer `libevdev-devel` for the
canonical headers; if absent, a small public-ABI declaration header allows linking
against the installed runtime. There is no private libevdev implementation here.

`make sanitize` additionally needs working `libasan` and `libubsan` packages. It
rebuilds binaries with instrumentation; run `make clean && make` before live trials.
These targets do not access physical input devices. Test files use synthetic
libevdev state, mocked event synchronization and captured virtual output.

## Read-only discovery and calibration

Review the code and [security notes](docs/security-review.md) first. On your host:

```sh
sudo ./palmreject --probe
sudo ./palmreject --observe
```

These modes never grab input and never create virtual devices. Observation expires
after 60 seconds. Automatic discovery requires a unique match; an optional
`--device /dev/input/by-id/...` must pass the same descriptor validation. The printed
`eventN` is a current location, not a stable identity. This branch deliberately
rejects other drivers/models rather than guessing their event semantics.

Observe ordinary fingers, thumbs, edge motions, multiple fingers and resting
palms. Record which samples are which. The output contains trackpad position and
size information; avoid publishing recordings unnecessarily. No keyboard events
are collected. `touch` on the installed driver is a proximity-derived value,
not generic physical pressure.

Copy `config/profile.example` to a local file and replace every placeholder with
values derived from your labeled observations. The example is deliberately invalid
until edited. Required fields:

| Field | Meaning |
| --- | --- |
| `width_threshold` | Global raw width threshold, 1–65535 |
| `touch_threshold` | Global raw touch/proximity threshold, 1–65535 |
| `edge_width_threshold` | Raw width threshold at the left/right edges, no greater than global width |
| `edge_percent` | Each side's fraction of measured X span, 1–25 percent |

Threshold comparisons are strictly greater-than. There are no defaults. Unknown,
duplicate, missing, out-of-range or shell-expression values are rejected. Config
files are parsed as data; they are never sourced or evaluated.

Check predictions without interception:

```sh
sudo ./palmreject --observe --config /absolute/path/to/profile.conf
```

`palm=1` reports that the frame contains a palm candidate; `palm=-1` means no
profile was supplied. Do not proceed if ordinary fingers are classified as palms
or the labeled palm cases are not detected.

## Supervised trials

Connect and test a **USB mouse and keyboard** first. Save current work and keep
another terminal open with the emergency stop ready:

```sh
sudo systemctl stop palmreject-trial.service
```

First test unfiltered forwarding:

```sh
sudo scripts/trial.sh --passthrough --recovery-ready
```

The acknowledgment means you have tested the independent recovery devices. The
launcher copies the built binary into a root-owned temporary directory, validates
the physical device, and starts a transient service. Both process and service have
60-second limits. Ctrl+C stops the service too. There is no automatic restart or
boot enablement. The service is ordered to stop before sleep/T2 suspend actions
and does not restart after wake.

The service initially has access only to uinput and the selected trackpad. After
virtual-device creation, the launcher verifies its sysfs identity and adds only
that virtual node to the runtime device allowlist. The process verifies libinput
recognizes it as a touchpad before grabbing. Readiness expires after 10 seconds.
This launch/allowlist handshake still needs host validation. Other keyboards and
mice are not added to the allowlist. Network access is isolated.

Lift all contacts and release buttons during startup. A contact appearing during
handover aborts the trial. Do not start a second instance alongside another filter.
The virtual device may need its own KDE settings; compare against the physical
trackpad's baseline, including tapping, acceleration and scrolling.

Verify pointer motion, taps, clicks, dragging, scrolling, pinch and KDE gestures.
Verify manual stop **and automatic expiry** restore the original trackpad before
trying filtering:

```sh
sudo scripts/trial.sh --filter --config /absolute/path/to/profile.conf --recovery-ready
```

Test the labeled palm cases, thumbs, edges, multiple fingers and palm arrival
mid-drag. Check for stuck clicks and normal operation after all contacts lift.
Do not enable routine use unless failure recovery also succeeds. The detailed
[plan](docs/fedora-macbookpro16-1-plan.md) lists acceptance and fault-injection tests.

The launcher requires root for the transient system service; the application
requires device access. It never modifies firmware, kernel modules, KDE settings,
keyd, force-click services, the input group or SELinux settings. It does not unload
uinput because other input software already uses it.

## Cleanup and limitations

The launcher stops the service and removes its runtime directory and temporary
unit properties when it exits. It refuses to replace an existing trial unit or its
drop-ins. `install.sh` is intentionally inert; permanent installation and automatic
resume are deferred until hardware acceptance. `uninstall.sh` prints recovery
instructions and does not delete older installations.

If the launcher is forcibly killed, first stop `palmreject-trial.service`. Inspect
that unit and its `/run/palmreject-trial.*` runtime directory before removing any
leftover artifacts. Nothing in this branch enables itself on reboot. Existing
upstream installations must be stopped separately before a trial; this branch's
scripts do not remove or migrate them.

Source review and bounded trials reduce risk; they do not guarantee that privileged
input software can never disrupt the session. On synchronization loss, the filter
releases virtual state and waits for physical contacts/buttons to become idle.
Disconnects and unrecoverable errors exit instead of repeatedly grabbing input.

GPL-3.0-only; original copyright notices are preserved in derived source files.
