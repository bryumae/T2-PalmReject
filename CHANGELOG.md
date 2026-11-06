# Changelog

## Fedora experimental adaptation

- Pin upstream review to 75b31901cf9e4c1e9336c51fc61347d988af5fe4.
- Add explicit probe/observe/passthrough/filter modes, strict physical-device
  validation, real capability cloning and measured calibration profiles.
- Add libevdev synchronization, bounded error recovery and safe palm button release.
- Replace automatic installation/sleep hooks with isolated 60-second trials.
- Add implementation plan, security review and offline filter/input/CLI tests.
- Hardware trials, sanitizer checks and persistent packaging remain pending.

## 1.0.0

- Working global palm lock for the tested T2 MacBook trackpad.
- Native libinput pointer motion and two-finger scrolling through a virtual
  multitouch touchpad.
- Physical click forwarding.
- Stable trackpad auto-detection for the Apple internal keyboard/trackpad.
- systemd service installation.
- Suspend/resume service restart hook.
- Optional keyboard-backlight restoration after resume.
- Uninstaller and dry-run installation check.
