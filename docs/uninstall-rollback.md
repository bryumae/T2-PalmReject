# Stop, uninstall and roll back

Stopping PalmReject, removing this checkout and restoring stock KWin are separate
choices. Preserve the measured profile, stock rollback RPMs, working custom RPMs,
source packages and logs unless you explicitly choose to remove them. Nothing in
this guide is executed automatically by `uninstall.sh`.

## Stop PalmReject only

Ctrl+C in the launcher terminal, or:

```sh
sudo systemctl stop palmreject-trial.service
```

Stopping closes the physical grab and removes the virtual touchpad on normal
cleanup. Lift contacts/buttons and verify physical input using the tested USB
recovery devices if needed. The launcher normally removes its runtime directory
and temporary unit properties when it exits. A missing unit is expected after
cleanup. Custom KWin can remain installed; stopping PalmReject does not require a
package transaction. No PalmReject boot service is enabled by this checkout.

If the launcher was forcibly killed, stop the service first and inspect:

```sh
systemctl status palmreject-trial.service --no-pager
systemctl cat palmreject-trial.service
systemctl show palmreject-trial.service -p ExecStart -p DropInPaths -p Result
journalctl -u palmreject-trial.service -n 80 --no-pager
sudo ls -ld /run/palmreject-trial.*
```

Identify the exact disposable `/run/palmreject-trial.*` directory and any runtime
unit properties from that invocation before removing leftovers. Do not delete
unrelated directories or revert a pre-existing unit blindly. The launcher refuses
to replace existing trial units/drop-ins; diagnose them before another launch.
These runtime files are separate from the retained checkout and calibration.

Older upstream installations may have persistent services/sleep hooks. This
adaptation does not remove or migrate them. Use their original installation
record/removal procedure; do not delete system files based only on a matching name.
Do not unload uinput: keyd and force-click software may use it.

## Remove local files only

There is no persistent PalmReject system installation from these scripts.
`install.sh` is inert. To retire this checkout, stop the trial, back up the profile
and recovery packages outside the checkout, and archive/move the directory first.
Deleting it would also delete ignored files: Git does not back up those files.

`make clean` removes the generated PalmReject executable and C test/analyzer
binaries only; it does not uninstall KWin, remove profiles or remove `artifacts/`.
Use it only if you explicitly want to discard those local binaries. Keep the
approximately 4.8 GB archived build tree and logs for recovery/review by default.
Avoid `git clean -fdx`, which would discard ignored personal files and artifacts.

## Restore stock KWin

Save work and stop the trial before changing packages. Use the existing
[stock rollback procedure](custom-kwin-build-test-install.md#11-restore-stock-kwin-if-necessary)
for the pinned 6.8.2 base; it restores the matching runtime packages together and
requires a normal logout/login. It also describes recovery from a text console.

After a desktop update, follow the
[update rollback procedure](custom-kwin-update.md#11-roll-back-a-failed-custom-update)
using stock RPMs matching that desktop base and any installed development/doc
subpackages. Do not blindly downgrade a newer desktop to the original 6.8.2 RPMs.
Removing `kwin` packages outright is not the rollback procedure.

Stock KWin lacks this cancellation API, so filtered startup should refuse to grab
input. Probe, observation and passthrough remain available. Retain your profile
and both working/stock package sets until you explicitly decide they are no longer
needed. Neither rollback path modifies T2 drivers, keyd or force-click settings.
