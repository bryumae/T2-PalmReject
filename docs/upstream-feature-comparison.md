# Upstream feature comparison and issue backlog

Audit date: 2026-11-08. This compares functionality in the original project with
this adaptation, not the current state of a particular installed service.

The upstream baseline is
[`75b31901cf9e4c1e9336c51fc61347d988af5fe4`](https://github.com/r2car/T2-PalmReject/tree/75b31901cf9e4c1e9336c51fc61347d988af5fe4),
confirmed as upstream `main` during this audit. The adaptation baseline is
[`ed0124690886e59672b6dfee977becc7e2cd0717`](https://github.com/bryumae/T2-PalmReject/tree/ed0124690886e59672b6dfee977becc7e2cd0717).
Source inspection establishes whether a capability exists; it does not establish
gesture quality, calibration accuracy or real-desktop acceptance.

## Input functionality

| Capability | Original project | This adaptation | Disposition |
| --- | --- | --- | --- |
| Global width and touch-major rejection | Independent hardcoded limits. | Independent measured profile limits. | Retained; touch-major here is proximity-derived. |
| Left/right edge-width rejection | One raw-X edge band. | One band normalized to measured X span, with configurable width limit. | Retained with different calibration. |
| Side plus upper-area rejection | Separate side and upper-area intersection. | No Y-dependent classifier or separate side band. | Missing classifier capability; spatial-region issue. |
| Extreme-side rejection | Additional narrow side region with its own width rule. | No distinct extreme-side region. | Missing classifier capability; spatial-region issue. |
| Far-upper-strip rejection | Additional upper strip with a width rule. | No upper-strip rule. | Missing classifier capability; spatial-region issue. |
| Combined width AND touch-major rejection | A conjunctive rule in addition to independent limits. | Only independent global and edge predicates. | Missing classifier capability; combined-detection issue. |
| Upper-area rejection with at least two contacts | Extra width predicate gated by physical contact count. | Physical count is not used by the classifier. | Missing classifier capability; contact-count issue. |
| Side rejection with at least two contacts | Extra width predicate gated by physical contact count. | Physical count is not used by the classifier. | Missing classifier capability; contact-count issue. |
| Global palm lock | Blocks all virtual contacts until physical contacts lift. | Blocks all contacts until physical contacts/buttons release; cancels tap gestures first. | Retained with cancellation and button-state safeguards. |
| Pointing with a finger while a palm remains down | Unsupported by the global lock. | Unsupported by the global lock. | Requested enhancement beyond upstream, not lost parity. |
| Pointer motion and physical clicking | Forwarded through a virtual touchpad. | Forwarded through a virtual touchpad. | Implemented; desktop settings and acceptance still matter. |
| Multitouch contacts and finger-count tool signals | Slot forwarding and one-to-five-finger tool signals. | Slot forwarding and the same tool-signal categories. | Implemented, not a missing gesture engine. |
| Scrolling, tapping, acceleration and desktop gestures | Handled by libinput/compositor. | Handled by libinput/KWin. | Same division of responsibilities; intermittent responsiveness needs investigation. |
| Thumb and pinch behavior | README explicitly notes limitations. | No separate thumb/gesture recognizer; uses measured classification and downstream recognition. | No evidence of a removed complete implementation; include these cases in responsiveness testing. |
| Pressure, minor axes and orientation | Advertises pressure and substitutes defaults/minor-axis values. | Clones actual device metadata and preserves supported values; omits absent pressure. | Deliberate event-fidelity change, not lost physical force-click support. |

The nine rejection clauses in
[upstream `is_palm_shape`](https://github.com/r2car/T2-PalmReject/blob/75b31901cf9e4c1e9336c51fc61347d988af5fe4/src/main.c#L155-L191)
map to three retained rule categories and six absent clauses, grouped into three
feature issues above. The
[current classifier and forwarding](https://github.com/bryumae/T2-PalmReject/blob/ed0124690886e59672b6dfee977becc7e2cd0717/src/filter.c#L56-L128)
show the corresponding implementation. Region recognition here means
position-dependent rejection thresholds, not programmable actions assigned to
touchpad areas.

The [original README](https://github.com/r2car/T2-PalmReject/blob/75b31901cf9e4c1e9336c51fc61347d988af5fe4/README.md)
delegates gestures to libinput and lists thumb/pinch limitations. Compare
[upstream virtual-device construction](https://github.com/r2car/T2-PalmReject/blob/75b31901cf9e4c1e9336c51fc61347d988af5fe4/src/virtual_touchpad.c)
with [this adaptation's capability cloning](../src/virtual_touchpad.c) before
treating advertised pressure or substituted contact sizes as hardware features.

## Reported responsiveness and requested coexistence

The user reports that gestures function but sometimes take longer or need a
second attempt. Specific gesture types, frequency, timing and a controlled
physical-input comparison have not been established. This is not evidence that
multi-finger forwarding is absent or that one particular classifier rule causes
the symptom.

The investigation should compare ordinary physical input, passthrough and
filtering with matching settings, correlating misses with contact state,
classification, lock transitions and downstream gesture recognition. A global
lock persisting while a palm stays down is a possible explanation for some
sequences, not a demonstrated diagnosis of this report. No live input experiments
were performed for this audit.

Selective rejection is a separate requested behavior: allow a finger to point
while a palm remains resting. It must preserve accepted contact identities/counts
and prevent accidental taps or stuck drags. Supporting this does not automatically
establish mixed palm-plus-multiple-finger gesture compatibility.

## Operational and platform differences

These differences are recorded for completeness; they are not part of the five
input-focused issues selected for publication.

| Area | Upstream behavior | Adaptation behavior and rationale |
| --- | --- | --- |
| Supported platform | Tested MacBook Air A2179, Arch and Hyprland. | Validates MacBookPro16,1 / 05ac:0340 with `t2_precision_trackpad`; filtered mode requires the KDE Wayland cancellation integration. Broad platform parity is outside this audit's issue scope. |
| Geometry and calibration | Hardcoded geometry, thresholds and fallback values. | Measured capabilities and required validated profile; upstream raw numbers are not portable defaults. |
| Build/install | Installer builds, including on privileged invocation; its dry-run also builds. | Build/test separately as the ordinary user; installer copies reviewed output and dry-run does not build or change services. |
| Device selection | Stable-link detection and installer `--device` override. | Strict rediscovery on every service start; manual probe/trials accept validated overrides. The persistent installer does not expose upstream's device override. |
| Configuration | Shell-style `/etc/palmreject.conf`, sourced by the sleep hook. | Numeric profile parsed as data plus UID settings; no shell evaluation. Paths/CLI are intentionally different. |
| Boot/login lifecycle | Enables a system service without a KWin session gate. | Enables a supervisor that waits for the configured Wayland session and verifies cancellation before grabbing input. |
| Restart after failure | `Restart=on-failure` with a short delay. | At the audited baseline, no automatic runtime retry loop. The current supervisor adds five delayed retries; see the [operation guide](palmreject.md#permanent-installation). |
| Suspend/resume | System-sleep hook with configurable fixed resume delay. | Logind sleep coordination and T2-service readiness; restore only previously healthy filtering. This replaces the old hook/delay interface. |
| Keyboard backlight | Optional `brightnessctl` restoration and related installer options. | No backlight management; existing T2/backlight services remain responsible. Convenience absent, not a palm-rejection feature. |
| uinput module setup | Runs `modprobe` and writes a boot module-load file. | Does not install module-load configuration or unload uinput; relies on the host making uinput available. Convenience absent. |
| Install/remove CLI | Interactive confirmation, `--yes`, `--force`, `--keep-config`; known-path removal. | Explicit profile/UID/stock-RPM inputs, manifest/backups and preserved configuration; stock-KWin rollback by default or `--keep-custom-kwin`. No destructive parity restoration is proposed. |
| Direct runtime invocation | Positional device path and indefinite execution. | Explicit modes, bounded supervised trials, or installed persistent supervision; probe/observe are read-only. |

Sources: [upstream installer](https://github.com/r2car/T2-PalmReject/blob/75b31901cf9e4c1e9336c51fc61347d988af5fe4/install.sh),
[service](https://github.com/r2car/T2-PalmReject/blob/75b31901cf9e4c1e9336c51fc61347d988af5fe4/systemd/palmreject.service),
[sleep hook](https://github.com/r2car/T2-PalmReject/blob/75b31901cf9e4c1e9336c51fc61347d988af5fe4/systemd/palmreject-sleep)
and [uninstaller](https://github.com/r2car/T2-PalmReject/blob/75b31901cf9e4c1e9336c51fc61347d988af5fe4/uninstall.sh);
current [installation tool](../scripts/manage-installation.py),
[supervisor](../scripts/service-manager.py) and [operation guide](palmreject.md).

## Issue backlog

Five reports cover the selected input work. Each includes source evidence,
acceptance criteria and scope boundaries; none claims these features are already
implemented. Contact-count rules depend on the spatial-region work. The
responsiveness investigation and selective-rejection enhancement are related,
but one is not assumed to solve the other.

| Issue | Classification |
| --- | --- |
| [#2 — Investigate intermittent gesture delay and gestures requiring a second attempt](https://github.com/bryumae/T2-PalmReject/issues/2) | Reported responsiveness; cause unconfirmed. |
| [#3 — Support finger pointing while a palm rests on the touchpad](https://github.com/bryumae/T2-PalmReject/issues/3) | Requested enhancement beyond upstream. |
| [#4 — Restore distinct side, upper-strip and corner palm-classification regions](https://github.com/bryumae/T2-PalmReject/issues/4) | Confirmed classifier-parity gap. |
| [#5 — Add combined width-and-proximity palm detection](https://github.com/bryumae/T2-PalmReject/issues/5) | Confirmed classifier-parity gap. |
| [#6 — Add contact-count-aware upper and side palm classification](https://github.com/bryumae/T2-PalmReject/issues/6) | Confirmed classifier-parity gap; depends on #4. |

No source behavior, installed package, running service, calibration or desktop
setting was changed by this audit. Personal profiles and input recordings are
excluded from the document and issue bodies.
