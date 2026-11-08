> Historical record: statements about installation, activation, defaults and
> pending checks describe stages of development, not current status. Start with
> the [README](../../README.md) and [current validation](../kwin-validation-2026-11-07.md).

# Fedora MacBookPro16,1 palm rejection adaptation

## Status and objective

Implement a reversible userspace adaptation of https://github.com/r2car/T2-PalmReject
for this machine. Preserve existing T2 drivers and desktop behavior. Do not activate
input interception until the safety gates below pass.

The fork and clone were created by the user. The implementation branch is
`fedora-macbookpro16-1-safety`, based on upstream commit
`75b31901cf9e4c1e9336c51fc61347d988af5fe4`. This plan is included in the checkout.
The source-level implementation and offline tests are now present; see
[the security/validation record](security-review.md). Nothing has been installed
or activated. Hardware calibration and live trials remain mandatory gates.
Persistent installation and automatic resume remain deferred until those pass.

Implementation adjustment: this machine has the libevdev runtime but no development
headers. The build prefers canonical headers and otherwise uses declarations of
only the stable public ABI subset it calls, linked to the installed runtime.
Sanitizer validation could not run because system sanitizer libraries are missing.

## Inspected environment

Observed on 2026-11-06:

| Component | Observation |
| --- | --- |
| Hardware | Apple MacBookPro16,1 |
| OS | Fedora 44 Workstation |
| Kernel | 7.2.15-200.fc44.x86_64 |
| Session | KDE, Wayland (despite Workstation OS branding) |
| Trackpad identity | Apple 05ac:0340, physical input2 interface |
| Current event node | event8, for observation only; never persist this number |
| Trackpad driver | t2_precision_trackpad |
| Existing input services | keyd; separate T2 force-click virtual keyboard |
| uinput | Already loaded and used by other software |
| SELinux | getenforce reports Disabled; do not change this configuration |

The keyboard and trackpad share their human-readable name. The force-click event
device is separate. The local driver source in `/usr/src/t2_precision_trackpad-0.01`
queries geometry from firmware, exports 16 multitouch slots, exports actual minor
axes and orientation, and intentionally does not export ABS_MT_PRESSURE. Its
ABS_MT_TOUCH_MAJOR signal derives from Q8 proximity. Verify live capabilities on
the host before implementing a device profile: sysfs/source observations are not
a replacement for EVIOCGABS and libinput inspection.

The agent sandbox exposes proc/sys metadata but hides `/dev/input`, `/dev/uinput`
and the system bus. Live input or systemd behavior cannot be validated here.

## Preliminary security review (superseded by the pinned local review)

Reviewed public pages, not a pinned complete checkout:

- `src/main.c`: output failures are ignored; SYN_DROPPED has no recovery;
  invalid slot numbers retain the previous slot; signal cleanup uses operations
  inappropriate in a signal handler; global palm suppression can defer button
  releases. The executable's default event7 path must be removed.
- `src/virtual_touchpad.c`: geometry, slot count, resolutions and axis ranges
  are hardcoded. Pressure is fabricated, minor axes are copied from major axes,
  and failures in multiple setup/event operations are ignored.
- `systemd/palmreject.service`: root execution without explicit isolation,
  Restart=on-failure, and no trial time limit.
- `install.sh`: rebuilds as root, writes unescaped option values into a config
  file, and enables/restarts the service immediately. Its dry-run still builds.
- `systemd/palmreject-sleep`: sources the config as root. Combined with unescaped
  configuration generation this permits command execution with crafted values.
  Do not reuse shell-sourced configuration.
- `uninstall.sh`: deletes known paths without restoring overwritten files.

No obvious networking/exfiltration code was observed in the reviewed runtime
sources. This does not certify the repository as secure. The Makefile could not
be retrieved, and public pages may have represented different revisions. The subsequent pinned local review is recorded in security-review.md; the
Makefile was inspected before building.

Reference pages:

- https://github.com/r2car/T2-PalmReject
- https://github.com/r2car/T2-PalmReject/blob/main/src/main.c
- https://github.com/r2car/T2-PalmReject/blob/main/src/virtual_touchpad.c
- https://github.com/r2car/T2-PalmReject/blob/main/install.sh
- https://github.com/r2car/T2-PalmReject/blob/main/systemd/palmreject.service
- https://github.com/r2car/T2-PalmReject/blob/main/systemd/palmreject-sleep
- https://github.com/r2car/T2-PalmReject/blob/main/uninstall.sh

## Repository workflow

1. Create or reuse `bryumae/T2-PalmReject` as a real GitHub fork of
   `r2car/T2-PalmReject`. Verify any existing repository's parent before using it.
2. Clone into a fresh directory; preserve upstream as a remote. Record the exact
   upstream commit SHA in the review document. Read all applicable AGENTS.md files.
3. Create branch `fedora-macbookpro16-1-safety`. Add this document under `docs/`.
4. Review the complete tree, Makefile, scripts and dependencies before invoking
   any build target. Build as the ordinary user; never run sudo make.
5. Implement and test below, commit related changes, and push this branch to the
   fork. Do not change upstream or enable input interception as part of publishing.

## Implementation

### Device identification and capabilities

- Validate Apple vendor/product, physical interface, pointer/buttonpad properties,
  multitouch capabilities and a nonvirtual sysfs ancestry. Reject keyboards,
  force-click nodes and virtual devices, including manual overrides.
- Require exactly one match. Prefer a validated stable link; where unavailable,
  rediscover from sysfs identity each run. Revalidate the opened descriptor to
  avoid a path-selection/open race. Remove all fixed event-number defaults.
- Query supported axes, their bounds/resolutions, key bits, properties and slot
  count from the opened device. Reject malformed or unsupported configurations
  before grabbing input. Create a distinctly named virtual touchpad.
- Preserve supported minor axes and orientation. Omit pressure when absent;
  never invent pressure or substitute defaults for valid zero samples.
- Preserve existing kernel, firmware, module parameters, keyd, force-click and
  T2 suspend configuration. No kernel/libinput patch is needed for the first trial.

### Interfaces and classifier

- Add `--probe`, `--observe`, `--passthrough`, `--filter`, and `--config` modes.
  Probe/observe must never grab input or create a virtual device. Reject ambiguous
  mode combinations; require explicit selection for interception.
- Parse configuration as data with validated, bounded numeric fields. Never
  source it in a shell or evaluate its contents as commands.
- Normalize edge regions using measured geometry. Calibrate width/proximity
  thresholds from labeled finger, thumb and palm samples on this driver. Do not
  activate the MacBook Air's raw constants as this machine's defaults.
- Initially retain upstream's global palm lock until all contacts lift. On lock,
  release all virtual contacts/buttons and discard deferred clicks. Document this
  behavior rather than promising simultaneous finger use while a palm is present.
- Keep calibration recordings limited to trackpad events; do not record keyboards.

### Event correctness and recovery

- Use libevdev state synchronization for SYN_DROPPED and initial state. Validate
  slot bounds and tracking transitions; never route invalid-slot data into the
  previously selected slot. Handle same-frame contact replacement correctly.
- Propagate all ioctl and output failures. Retry EINTR appropriately and use a
  bounded policy for output backpressure. Unrecoverable failures must exit and
  close the physical descriptor promptly rather than retain its grab.
- Use signal flags and normal-loop cleanup. Release virtual contacts/buttons,
  release the physical grab, and destroy the virtual device on exit.
- Verify udev discovery and libinput touchpad classification before handover.
  Require all contacts/buttons released when grabbing. Abort if readiness cannot
  be established; do not replace readiness checks with a fixed sleep.

### Trial service and installation

- Use a transient system service named `palmreject-trial.service` with Restart=no,
  RuntimeMaxSec=60, TimeoutStopSec=2 and whole-service termination. The runtime
  cap must remain independent of the filter event loop.
- Restrict device access to the selected physical trackpad and uinput, deny
  networking, protect filesystems and prohibit privilege escalation. Do not add
  the user to the input group or grant access to every input device. Validate
  that service isolation still permits the required ioctls.
- Do not install boot services, sleep hooks, persistent udev overrides or module
  loading configuration for initial trials. Do not unload uinput on cleanup.
- After successful trials only, provide an optional root-owned installation with
  an artifact manifest, backups of replaced files and exact rollback. Build
  unprivileged; copy only reviewed artifacts into system paths. Leave startup
  disabled by default. Validate config ownership and avoid writable executables
  in a privileged service's execution path.
- For later suspend support, order stopping before existing T2 hardware suspend
  actions and rediscovery after resume completion. Restart only if previously
  active; leave ordinary manual stops stopped. Avoid racing an independent
  system-sleep script against existing Kait2en/T2 units. Omit backlight changes.

## Validation and acceptance

1. Audit the complete pinned tree before build; check dependencies and compiler
   warnings/static analysis. Use Fedora compiler/Linux headers/make plus
   libevdev-devel. Run meaningful event-processing tests with address and
   undefined-behavior sanitizers; mock input/output so tests do not grab hardware.
2. Cover normal multitouch, slot reuse/replacement, invalid slots, dropped frames,
   missing axes, valid zero values, disconnects, signals, read/write/setup errors,
   palm lock entry/exit and button release during suppression.
3. On the host, record baseline capabilities, libinput classification, KDE settings
   and existing T2 service state without changing them. Probe/observe while the
   physical trackpad continues normal operation; collect labeled calibration data.
4. The user selected USB mouse + keyboard for recovery. Verify both before a live
   trial and keep a second terminal ready with:

   ```sh
   sudo systemctl stop palmreject-trial.service
   ```

5. First run 60-second passthrough only. Confirm manual stop and automatic expiry
   restore physical input before attempting filtering. Verify cursor motion,
   tapping, physical clicks/dragging, scrolling, pinch and KDE gestures. The new
   virtual device may need its own KDE settings; compare with the saved baseline.
6. Run a separate 60-second filtering trial. Test typing with resting palms,
   ordinary fingers/thumbs at edges, multiple fingers and palm arrival mid-drag.
   Require no stuck clicks and recovery after all contacts lift. Accept only if
   the labeled palm cases are rejected and agreed ordinary-finger cases succeed.
7. Test normal stop, process crash, SIGKILL and injected output failure. Verify
   the original trackpad returns without automatic restart; target recovery within
   three seconds of a stop request. Stop further trials if recovery fails.
8. Test suspend separately, initially stopping before sleep and leaving the
   filter stopped after wake. Validate ordered integration only after recovery
   and hardware rediscovery are proven.

Acceptance evidence must include the pinned SHA, build/test commands and results,
calibration profile and labeled cases, trial expiration and recovery outcomes,
and a manifest of any later persistent artifacts. Do not label hardware tests
as passed when only offline tests ran.

## Rollback and limits

Stopping the transient service must close the grab and restore the physical
trackpad. No persistent service means a reboot does not start the trial again.
For an optional later installation, stop/disable its units and remove only its
manifested artifacts, restoring any backups. Preserve pre-existing T2, keyd,
force-click, desktop and security settings.

These controls reduce disruption and make recovery testable. They cannot
guarantee privileged input software will never affect the system. Host capability
measurements and a complete pinned-source review are required before activation.
