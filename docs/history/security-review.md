> Historical record: statements about installation, activation, defaults and
> pending checks describe stages of development, not current status. Start with
> the [README](../../README.md) and [current validation](../kwin-validation-2026-11-07.md).

# Security review and validation record

## Reviewed baseline

Upstream: `r2car/T2-PalmReject`

Commit: `75b31901cf9e4c1e9336c51fc61347d988af5fe4`

The local tracked tree contains two C implementations, a header, Makefile, shell
installation/detection/removal scripts, systemd integration, documentation and a
GPL license. No submodules, binary downloads, dependency-fetching build targets or
network calls were present in the reviewed build/runtime/install files. The
Makefile compiles locally. This is a source review, not an independent security
audit or proof of absence of vulnerabilities.

## Findings and disposition

| Finding | Disposition in this branch |
| --- | --- |
| Root build and automatic service enablement | Automatic installer disabled; build unprivileged; transient trials only |
| Unescaped configuration written then sourced as root | Removed sleep hook; strict numeric data parser; no shell evaluation |
| Name-based selection and raw event-number default | Physical driver/interface, USB identity and capabilities checked on opened descriptor; ambiguous detection rejected |
| Air-specific geometry and fabricated pressure/minor axes | Actual device metadata cloned; supported axes retained; absent pressure omitted |
| Ignored setup and output failures | Propagated; failed output exits and closes physical FD before virtual cleanup |
| Unsafe signal cleanup | Signal flag; normal-loop cleanup; independent systemd termination limit |
| SYN_DROPPED and stale state | libevdev sync; release virtual state and wait for idle before forwarding again |
| Button held during global palm lock | Release immediately; suppress stale presses until physical release |
| Failure restart loops | Restart=no; 60-second service lifetime; no automatic resume |
| Broad root process access | Exact device allowlist, protected filesystem, empty capability set, isolated network |
| Uninstaller deletes potentially preexisting files | No persistent installer/removal in this experimental branch |

The small `evdev_api.h` fallback declares public libevdev 1.x ABI functions only.
It links against the installed library rather than providing an independent event
parser. Canonical upstream headers are preferred when installed.

## Checks actually performed

- Normal GCC build with `-Wall -Wextra -Werror` passed.
- C filter/config suite passed: edge normalization, palm lock, button release,
  tracking replacement, no invented pressure, zero samples, malformed profiles,
  invalid slot count and failure at every output operation in a synthetic frame.
- Input suite passed using synthetic libevdev devices and mocked sync reads:
  initial/multitouch snapshots, absent pressure, coordinate/tracking bounds,
  button-only nonidle state, dropped-frame sync completion, disconnects,
  cancellation, and actual failed writes to `/dev/full`/an invalid FD.
- Seven Python CLI/shell checks passed: explicit mode selection, missing/duplicate
  arguments, unsupported device rejection, inert installer dry run, shell syntax,
  help and trial-recovery acknowledgment.
- GCC `-fanalyzer` build completed without diagnostics.
- Address/undefined sanitizer build attempted but could not link: the installed
  linker files reference missing `libasan.so.8.0.0` and `libubsan.so.1.0.0`.
  Sanitizer validation is pending, not passed. No system packages were changed.

## Required host gates — not performed here

The sandbox cannot access `/dev/input`, `/dev/uinput` or the system bus. Therefore
all of these remain unverified:

1. Live descriptor identity, ranges/resolutions and axis semantics.
2. Labeled calibration separating fingers/thumbs from palms.
3. Virtual-device udev and libinput classification on KDE.
4. The launcher's systemd isolation, dynamic device allowlist and readiness
   handshake (including effective access to all three allowed nodes).
5. Passthrough behavior for tapping, clicking, dragging, scroll, pinch and gestures.
6. Filtering performance and absence of false positives in the labeled cases.
7. Physical-input recovery after stop, expiry, crash, SIGKILL and output failure;
   target at most three seconds after stop.
8. Stopping before existing T2 suspend actions and remaining stopped after wake.

No trial may be described as safe or hardware-validated until these gates pass.
The user selected independent USB mouse and keyboard recovery for live tests.
The empty capability set may expose host-specific ioctl requirements; if so,
fail the trial and investigate rather than broadening permissions automatically.

## KWin cancellation implementation (2026-11-07)

The host (outside the agent sandbox) has SELinux **Enforcing**. An audit record
confirmed the trial binary originally ran as `init_t` and was denied opening
`event_device_t`. The launcher now labels only its disposable executable copy
`bin_t`; it does not change enforcement or install policy. Earlier reports of
Disabled came from the sandbox and do not describe the host's enforcement.

Palm rejection now requires a successful compositor cancellation acknowledgement
before virtual liftoffs or button changes. A versioned, sequence-checked Unix
socket protocol links the root filter to an unprivileged session helper. Each
side checks peer credentials; the helper verifies the exact virtual device and
pins KWin's D-Bus owner. No input events or profile values are sent to the helper.
The root filter never accesses the desktop bus. Helper failure ends the trial;
cancellation has a 100 ms reply limit. Startup negotiation happens before grabbing.

The KWin patch and pinned Fedora source-package recipe are under `packaging/kwin`.
Normal tapping preferences remain enabled and are not written during cancellation.
Raw liftoffs are buffered until the physical frame has been classified, including
same-frame slot replacement. Synchronization loss and orderly filtered shutdown
also request cancellation; physical-input release takes priority during cleanup.

Normal filter/input/CLI tests, new cancellation-order and Unix socket
authentication/protocol tests, Python helper tests, and GCC static analysis passed.
Address/undefined-behavior sanitizer tests passed in a temporary copy outside the
sandbox (which blocks Unix socket sends). The checkout binary remains a normal,
uninstrumented build. Fedora source RPM signatures were verified and source
preparation applies the KWin patch without fuzz. All 307 KWin device-test cases
passed on an isolated test D-Bus, including the new reset and D-Bus-reply checks.
The cancellation method queues work on the compositor thread and uses a delayed
reply, avoiding an input-thread shutdown deadlock. Full KWin RPM packaging and its
test stage passed. Runtime RPM digests, normalized dependencies, payload paths
(apart from build-ID links), scriptlets and file capabilities were checked against
the saved stock packages. A DNF preview upgrades only the three KWin runtime
packages, with no additional dependency changes. Desktop gesture acceptance is
still pending.
No custom KWin package has been installed or running compositor replaced.

## Deferred after hardware acceptance

Persistent packaging with a manifest and backups, boot enablement, and optional
ordered restart after resume. No changes to firmware, kernel/libinput source,
existing input groups, SELinux state, keyd or force-click behavior are proposed.
