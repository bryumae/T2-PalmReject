# T2 PalmReject — Fedora MacBookPro16,1

Experimental userspace palm rejection for **MacBookPro16,1, Apple 05ac:0340**,
using `t2_precision_trackpad` on **Fedora 44 / KDE Wayland**. Other models and
drivers are deliberately rejected. Derived from
[r2car/T2-PalmReject](https://github.com/r2car/T2-PalmReject), reviewed at
`75b31901cf9e4c1e9336c51fc61347d988af5fe4`.

## Supported environment

This adaptation targets the Apple T2 trackpad identity and driver listed above.
It uses Linux evdev/uinput, libevdev, libinput and systemd. Filtered operation also
requires KDE Wayland, Python D-Bus bindings and the companion KWin patch. The
packaging recipe is pinned to **Fedora kwin-6.8.2-3.fc44**; a different KWin base
requires source review, patch adaptation and testing. This is not a general-purpose
palm-rejection tool for arbitrary touchpads or desktops.

## Current status

Implemented features include validated device discovery, read-only observation,
calibration profiles, unfiltered forwarding, global palm rejection and a bounded
manual launcher, plus persistent login/resume operation. The KWin integration implements tap/drag cancellation while
preserving tapping preferences and the virtual device.

Automated PalmReject tests, static analysis, the custom KWin package build and
isolated KWin tests have passed; see the
[dated validation report](docs/kwin-validation-2026-11-07.md) for evidence and scope.
**Complete desktop acceptance remains unfinished**, including drag-lock
cancellation, input recovery and screen sharing. Reported input and rendering
warnings remain unresolved. Passing automated checks does not establish that all
real-desktop behavior is correct.

Simultaneous pointing with a resting palm is unsupported. The installer enables
session-aware filtering at login and restores a healthy running session after
suspend. Runtime failures release input and stay stopped until a new login or
manual restart. There is no automatic KWin rebuild service. Installing custom
KWin and launching PalmReject are separate operations.

## Getting started

Build as your ordinary user after installing the dependencies listed in the
[PalmReject guide](docs/palmreject.md#dependencies-and-local-build):

```sh
make
make test
make analyze
```

Next, follow that guide to discover the trackpad, collect labeled observations
and create a measured calibration profile. The example profile is intentionally
invalid until edited; there are no universal threshold defaults. Live modes use
`scripts/trial.sh`, with a default duration of 60 seconds and an explicit recovery
acknowledgment. Test passthrough and physical-input recovery before filtering.
Filtering requires the [custom KWin integration](packaging/kwin/README.md).
After supervised checks, use the [permanent installation procedure](docs/palmreject.md#permanent-installation)
to install root-owned copies and enable `palmreject.service`. The uninstaller
restores verified matching stock KWin by default; `--keep-custom-kwin` removes
PalmReject alone.

## Guides

- [Build, calibrate, launch, stop and update PalmReject](docs/palmreject.md)
- [Build, test and install custom KWin](docs/custom-kwin-build-test-install.md)
- [Maintain custom KWin through Fedora updates](docs/custom-kwin-update.md)
- [Troubleshoot by symptom](docs/troubleshooting.md)
- [Stop, uninstall local files or restore stock KWin](docs/uninstall-rollback.md)
- [KWin cancellation design and packaging](packaging/kwin/README.md)
- [Dated validation and remaining acceptance checks](docs/kwin-validation-2026-11-07.md)
- [Historical implementation and security records](docs/history/README.md)

## How input flows

```text
Physical T2 trackpad → PalmReject classifier → virtual touchpad → KWin/libinput → applications
                              ↓                                  ↑
                        session helper → patched KWin tap cancellation
```

PalmReject validates and exclusively grabs only the physical trackpad during live
operation. It clones measured capabilities into **PalmReject MacBookPro16,1 Touchpad**;
KWin/libinput supplies pointer motion, tapping, scrolling and desktop gestures.
Probe/observation never grab input or create a virtual device. Passthrough forwards
without palm classification. Filtering requires a measured calibration profile
and the patched KWin cancellation API before the physical grab.

A detected palm locks the **whole virtual trackpad** until all physical contacts
and buttons release. Simultaneous pointing with a resting palm is unsupported.
Before suppressing contacts, PalmReject asks an unprivileged session helper to
cancel pending taps and tap-generated dragging in patched KWin. Tap-to-click
preferences stay enabled, drag lock is cancelled even after fingers lift, and the
virtual device stays connected. A cancelled drag can drop an item at its current
position; cancellation cannot undo actions already delivered to applications.
Missing integration or a cancellation failure ends filtering.

Separate T2 force-click virtual keyboards and keyd are outside this path.
PalmReject neither reads those keyboards nor changes their services or settings;
force-click actions are not covered by the virtual touchpad's cancellation.

The trial launcher creates a **temporary systemd service** named
`palmreject-trial.service`, with device restrictions and an independent duration
limit. Permanent installation uses `palmreject.service` to supervise the restricted
`palmreject-input.service` and the desktop-user helper, without a trial expiry. `journalctl` reads its logs; it does not launch it. Stop/exit releases the
physical grab. Unrecoverable output errors release physical input; synchronization
loss resets virtual state and waits for idle. Recovery still needs hands-on checks.

## Repository map

| Path | Role |
| --- | --- |
| `README.md` | Project overview, supported environment and feature status. |
| `docs/palmreject.md` | Local build, calibration and manual operation. |
| `docs/custom-kwin-build-test-install.md` | Pinned custom KWin build, install and acceptance procedure. |
| `docs/custom-kwin-update.md` | Fedora updates, patch rebasing and new builds. |
| `docs/troubleshooting.md` | Diagnostics and symptom-specific fixes. |
| `docs/uninstall-rollback.md` | Stop, local removal and stock KWin recovery. |
| `docs/kwin-validation-2026-11-07.md` | Retained dated evidence and open findings. |
| `docs/history/` | Historical implementation plan and security review, not current setup instructions. |
| `src/main.c` | CLI, physical discovery, event loop and trial lifecycle. |
| `src/filter.c` | Profile parser, classifier and global palm lock. |
| `src/virtual_touchpad.c` | Capability validation/cloning and virtual output. |
| `src/gesture_control.c` | Authenticated helper protocol and cancellation acknowledgment. |
| `include/virtual_touchpad.h` | Shared device, profile and filter declarations. |
| `include/gesture_control.h` | Cancellation protocol declarations. |
| `include/evdev_api.h` | Public libevdev ABI fallback when development headers are absent. |
| `scripts/trial.sh` | Bounded transient-service launcher and cleanup. |
| `scripts/detect-trackpad.sh` | Prints a validated physical node using the built program. |
| `scripts/gesture-helper.py` | Unprivileged bridge to device-scoped KWin D-Bus cancellation. |
| `scripts/service-manager.py` | Session/sleep lifecycle, restricted worker and helper supervision. |
| `scripts/manage-installation.py` | Manifest-based installation, upgrade, removal and verified stock rollback. |
| `systemd/palmreject.service` | Root supervisor service enabled by installation. |
| `scripts/build-kwin.sh` | Pinned KWin RPM build wrapper, four jobs by default. |
| `packaging/kwin/README.md` | Integration design and build references. |
| `packaging/kwin/prepare.py` | Verifies pinned source RPM and prepares custom spec/source RPM. |
| `packaging/kwin/0001-palmreject-cancel-tap-gestures.patch` | KWin implementation and regression tests. |
| `tests/test_filter.c`, `tests/test_input.c`, `tests/test_gesture.c` | Offline C tests. |
| `tests/test_cli.py`, `tests/test_helper.py` | CLI and helper tests. |
| `tests/test_service.py`, `tests/test_installation.py` | Mocked lifecycle and temporary-root installation/rollback tests. |
| `config/profile.example` | Trackable, deliberately invalid calibration template. |
| `config/` personal profiles | Private local configuration; ignored by Git. |
| `Makefile` | Local build, tests, analysis and sanitizer targets. |
| `install.sh`, `uninstall.sh` | Installer/uninstaller entry points; both support `--dry-run`. |
| `.gitignore` | Generated output, personal configuration and editor/cache exclusions. |
| `CHANGELOG.md`, `VERSION` | Adaptation changes and inherited upstream release metadata. |
| `LICENSE` | GPL-3.0-only; original notices retained in derived sources. |
| `palmreject`, `tests/test-filter`, `tests/test-input`, `tests/test-gesture`, `tests/palmreject-analyzed`, `*.o` | Ignored generated executables/objects. |
| `artifacts/kwin/` | Local source RPM inputs. |
| `artifacts/kwin-build/` | Generated spec, source, RPMs, logs and original validation manifest. |
| `artifacts/kwin-build-backup-*/` | Optional archived build trees and test programs. |
| `artifacts/kwin-stock/` | Preserved stock rollback RPMs. |
| `artifacts/kwin-audit-*/` | Local audit/test/rendering evidence. |

Source, tests, patch, packaging recipe and guides are maintained files. Binaries,
Python caches, archives and `artifacts/` are generated local output; personal
profiles are configuration. Build artifacts and recovery packages are local files,
not prerequisites supplied by a fresh clone. Generated validation manifests are
**not automatically refreshed by rebuilding**: record new hashes/results before
using an old manifest to assess new RPMs.

Machine-specific installation details and session observations can be kept in
`DEVICE-STATUS.local.md`, which is ignored by Git. The dated validation report is
retained as historical test evidence rather than a live status report.

---

Note: ChatGPT was used to assist with development and documentation of this repository.
