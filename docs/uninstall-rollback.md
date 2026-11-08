# Stop, uninstall and roll back

Stopping PalmReject, removing this checkout and restoring stock KWin are separate
choices. Preserve the measured profile, stock rollback RPMs, working custom RPMs,
source packages and logs unless you explicitly choose to remove them. Nothing in
the manual rollback section is executed unless you invoke the uninstaller below.

## Stop PalmReject only

For a permanent installation:

```sh
sudo systemctl stop palmreject.service
```

To remove boot activation as well, use `sudo systemctl disable --now palmreject.service`.
Stopping the supervisor also stops its bound input worker/helper; it stays stopped
until explicitly started or the next boot. Custom KWin can remain installed.

For a trial, Ctrl+C in the launcher terminal, or:

```sh
sudo systemctl stop palmreject-trial.service
```

Stopping closes the physical grab and removes the virtual touchpad on normal
cleanup. Lift contacts/buttons and verify physical input using the tested USB
recovery devices if needed. The launcher normally removes its runtime directory
and temporary unit properties when it exits. A missing unit is expected after
cleanup. Custom KWin can remain installed; stopping PalmReject does not require a
package transaction. Trial cleanup does not uninstall a permanent service.

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

## Uninstall the permanent installation

Preview first, then run removal when ready. **The default also restores stock KWin**:

```sh
sudo ./uninstall.sh --dry-run
sudo ./uninstall.sh
```

Without the checkout, the installed equivalent is:

```sh
sudo /usr/local/sbin/palmreject-uninstall --dry-run
sudo /usr/local/sbin/palmreject-uninstall
```

To stop/disable/remove PalmReject while keeping custom KWin:

```sh
sudo ./uninstall.sh --keep-custom-kwin
```

The uninstaller validates the root-owned manifest and, for default removal, the
saved stock RPM hashes/signatures and exact installed desktop base/architecture.
It disables/stops PalmReject, restores all matching KWin subpackages together
using the saved local RPMs with repositories disabled, then removes only
manifested program/unit files. It does not kill KWin or log you out. Log out/in
normally after package rollback; until then the existing compositor keeps running.

Calibration/settings in `/etc/palmreject/`, records/backups and stock RPMs in
`/var/lib/palmreject/`, and every checkout/profile/build artifact remain intact.
Modified installed program/unit files are reported and preserved. If the DNF
transaction fails, filtering stays disabled and the installed uninstaller/records
remain for a retry. Dry-run performs no file, service or package changes.

After a later desktop update, stale RPMs are refused rather than downgrading to
an unrelated base. Refresh the installation with a reviewed matching rollback set,
or use `--keep-custom-kwin` and follow the manual package rollback procedure below.
The uninstaller does not remove an unrecognized older upstream installation.

## Remove local files only

Stop the trial or permanent service before retiring the checkout. Back up the
profile and recovery packages outside the checkout, and archive/move the directory
first. Deleting it also deletes ignored files: Git does not back them up. A permanent
installation uses independent root-owned copies and must be uninstalled separately.

`make clean` removes generated PalmReject and C test/analyzer binaries only. It
does not uninstall the service/KWin or remove profiles/artifacts. Avoid
`git clean -fdx`, which discards ignored personal files and recovery packages.

## Restore stock KWin

Save work and stop/disable the permanent supervisor (or stop the trial) before
changing packages manually. Use the existing
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
