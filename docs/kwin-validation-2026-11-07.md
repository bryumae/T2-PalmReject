# KWin and PalmReject validation — 2026-11-07

## Result

No confirmed general KWin regression was found by these checks. This is a partial
validation, not evidence that every desktop feature works. Real-session logs have
unresolved input and rendering warnings that deserve follow-up if there are
visible symptoms. No desktop preferences, packages or running input grabs were
changed during this review.

## Checks that passed

- Installed `kwin`, `kwin-common` and `kwin-libs` are all
  `6.8.2-3.palmreject1.fc44`; `rpm -V` reported no package-file differences.
- Running KWin owns its session D-Bus name and exposes `cancelTapGestures` on the
  actual PalmReject virtual device. Its reported compositing backend is active
  OpenGL ES on Intel UHD Graphics 630 / Mesa 26.2.6.
- No KWin coredumps were found. No assertion, deadlock or cancellation-method
  failure was found in the queried KWin service logs.
- All PalmReject C suites, 9 CLI tests, 3 helper tests and GCC static analysis
  passed with the latest local code.
- Five archived KWin test programs passed on an isolated D-Bus: Device 307,
  KeyEvent 5, PointerEvent 24, TouchEvent 9 and GestureEvent 16. Total: **361
  passed, zero failed or skipped**. The archived validation's patch hash and the
  installed build's source patch both match the current repository patch.
- Archived CTest files retained absolute paths to the original build directory.
  The first CTest invocation therefore reported executables not found. Running
  the actual archived binaries directly resolved that test-harness path issue;
  it was not a code-test failure.
- A separate virtual KWin, private configuration/runtime directories and isolated
  D-Bus rendered an animated QtQuick Wayland window: **181 frame swaps in three
  seconds**, with both client and compositor exiting successfully. No swapchain
  allocation warning was reproduced in the final rendering test.
- The actual virtual touchpad reports tapping and tap-and-drag enabled. Drag lock
  is currently disabled; its real-session cancellation was not exercised.
- The current filtered trial reports active/success. PipeWire, the desktop portal
  and `plasma-xdg-desktop-portal-kde` are running, with portal D-Bus owners present.
  Service availability alone does not establish successful screen sharing.

The production compositor's archived compiler flags do not contain
`KWIN_BUILD_TESTING` or `KWIN_UNIT_TEST`: enabling the test subtree did not put the
production compositor in its test mode.

## Findings still open

### Touch jumps and tracking-ID warnings

Libinput has discarded touch jumps from both physical `event8` and the virtual
PalmReject device. Physical-device touch jumps also occurred under the earlier
KWin process, before this custom build. This is evidence that the physical jump
problem predates the cancellation patch; it does not prove that forwarding adds
no further problems.

There are also physical-device duplicate tracking-ID `-1` warnings. Handover
around an exclusive grab and the underlying T2 event stream are candidates to
investigate, not established causes. The review did not record raw physical input
or change the driver. A labeled reproduction comparing ordinary physical use,
passthrough and filtering is needed if pointer jumps or stuck contacts occur.

### Graphics-buffer allocation warnings

The real compositor logged intermittent `Failed to allocate a graphics buffer
for a swapchain` messages and unsupported-window-mask messages. The cancellation
patch does not edit rendering code, and isolated animated rendering passed.
Neither fact proves that the real-session warnings are harmless or unrelated to
this build. Their cause remains unresolved; a reproducible UI action and, if
necessary, a controlled stock/custom comparison are required.

AMD reset messages around 21:14 occurred during device resume, followed by
`PM: suspend exit`. They are not by themselves evidence of a new compositor
crash. The active compositor reports the Intel renderer.

### Scope of isolated graphics testing

The initial isolated desktop test attempted to activate portal services that
could not operate in the throwaway session. The final test avoided the KDE
platform theme and explicitly confirmed rendered frames. Its missing PipeWire
context and shutdown render-query warning belong to that isolated run. They do
not demonstrate a broken main-session portal; actual portal services were checked
separately and were running. Screen sharing itself remains untested.

## Hands-on checks still required

Use a harmless window/disposable drag target with USB recovery devices ready:

1. Confirm ordinary taps, multi-finger taps, physical clicks, scrolling, pinch and
   KDE gestures. Check menus, Overview and full-screen transitions for flicker.
2. Trigger rejection during a brief tap, during tap-and-drag, and with drag lock
   enabled after fingers lift. Require no extra click, a matching button release,
   and normal tapping after all physical contacts/buttons release.
3. Verify stop, expiry, lock/unlock and suspend/resume recovery. Do not infer
   successful input recovery from a service status alone.
4. Try a short screen-sharing/screen-recording session through an application you
   normally use, and any external-display workflow you depend on.

The review did not inject gestures into the user's live desktop, stop the active
trial, enable drag lock, restart KWin or switch installed packages for an A/B test.

## Evidence

- Offline test summary: `artifacts/kwin-audit-20261107/test-results.txt`.
- Isolated rendering log: `artifacts/kwin-audit-20261107/render.log`.
- Package build and package test-stage log: `artifacts/kwin-build/build.log`.
- Source patch: `packaging/kwin/0001-palmreject-cancel-tap-gestures.patch`.

Generated evidence under `artifacts/` is local and Git-ignored.
