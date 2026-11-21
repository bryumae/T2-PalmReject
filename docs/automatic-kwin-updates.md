# Automatically rebuild KWin after Fedora updates

On Fedora 44 x86_64, you can opt in to rebuilding and installing the PalmReject
patch whenever Fedora installs a stock KWin build. This also works when you've
already updated and PalmReject reports `KWin lacks cancelTapGestures`.

The updater builds against the exact installed KWin release, runs the
cancellation tests, and installs the matching KWin RPMs together. Before replacing
them it saves the signed stock RPMs for rollback. **Log out and back into KDE
after the journal reports a successful installation.** That loads the new
compositor, and the enabled PalmReject supervisor can start filtering for the
new session. A rebuild can take several minutes or longer and needs several
gigabytes of disk space.

## Enable

From the repository, build PalmReject and follow the
[build dependency instructions](custom-kwin-build-test-install.md) for KWin.
Install the KWin build dependencies for the current stock release, using its
signed source RPM and Fedora spec as described in the
[manual update guide](custom-kwin-update.md#6-review-the-new-fedora-source-before-adapting-the-patch).
The builder uses these host dependencies. It runs under a dedicated system account in a separate
systemd service with a private network, home and temporary directory. Install
`dbus-daemon`, the provider of `cmake(Qt6WaylandClientPrivate)`, and
`python3-libdnf5` if missing. Fedora's optional `libdnf5-plugin-actions` package
queues the build after a DNF5 transaction. The timer checks at boot and every
15 minutes, including when the plugin is absent or an update is applied offline.

Use your existing calibrated profile:

```sh
make
sudo ./install.sh --dry-run --enable-kwin-updates --config "$PWD/config/my-profile.conf"
sudo ./install.sh --enable-kwin-updates --config "$PWD/config/my-profile.conf"
```

If KWin is already patched, supply `--stock-rpm-dir DIR` if the matching
stock RPMs aren't in `artifacts/kwin-stock`. If KWin is stock, the updater
downloads the rollback set itself. Run the updater immediately if desired:

```sh
sudo systemctl start --no-block palmreject-kwin-update.service
journalctl -f -u palmreject-kwin-update.service -u palmreject-kwin-build.service
```

After the next login, check for `Filtering for session …`:

```sh
systemctl status palmreject.service palmreject-input.service --no-pager
```

## Diagnose and retry

```sh
systemctl list-timers palmreject-kwin-update.timer
journalctl -b -u palmreject-kwin-update.service -u palmreject-kwin-build.service --no-pager
```

The updater supports source and spec layouts compatible with its reviewed build
recipe. It checks the Fedora signature, exact source release, touched files
against the reviewed fingerprints, patch application, test results, and RPM
interfaces. Missing sources or a newer package transaction leave Fedora's stock
build in place. Changes in the input code, package layouts, or test failures
require review. This can leave PalmReject idle with the physical trackpad still
available. Use the [manual update guide](custom-kwin-update.md) to rebase the
patch, review the affected input code, and update the recipe and
`packaging/kwin/reviewed-input.json` before reinstalling the updater.

After correcting a local build failure, such as an absent build dependency,
request one fresh attempt for the same release:

```sh
sudo touch /var/lib/palmreject/kwin-update-retry
sudo systemctl start --no-block palmreject-kwin-update.service
```

## Disable or roll back

Disable the timer first. This also prevents the DNF hook from starting the
updater or an in-flight build from starting an installation. Wait for any package
transaction already in progress to finish before changing KWin.

```sh
sudo systemctl disable --now palmreject-kwin-update.timer
systemctl status palmreject-kwin-update.service --no-pager
```

Disabling the timer keeps the installed KWin and PalmReject service. The
[uninstaller](uninstall-rollback.md) stops the updater and restores the saved
matching stock RPMs unless you pass `--keep-custom-kwin`. Log out and back in
after restoring stock KWin. The locked build account is retained with its cache.
The next ordinary Fedora update can replace the
custom build without any version locks.
