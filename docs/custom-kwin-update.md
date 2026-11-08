# Update custom KWin

There is no automatic patch-rebase or rebuild service in this repository. The
current preparation script accepts only **kwin-6.8.2-3.fc44**. A future Fedora
KWin update can replace the custom package without carrying its cancellation
method forward.

There are two parts to this guide: ordinary Fedora updates, then maintaining a
new custom build. The latter requires source-code review and may require C++
changes. A failed patch application cannot be solved safely by a universal command.

Use Bash in Konsole. Build as your ordinary user; use `sudo` only for system
package operations. For the current pinned build, see the
[build/test/install guide](custom-kwin-build-test-install.md).

## 1. Record what is installed and stop a trial

```sh
cd "$HOME/Documents/T2-PalmReject"
rpm -q kwin kwin-common kwin-libs libinput
rpm -q kwin-devel kwin-doc
git status --short
sudo systemctl stop palmreject.service
sudo systemctl stop palmreject-trial.service
```

An absent trial unit is normal. Save your work before updating desktop packages.
Preserve uncommitted work before changing the patch or preparation script; do not
reset the checkout or delete your calibrated profile.

Keep the exact RPMs for your working custom build, its patch/spec and test logs.
The first build's runtime RPMs are in `artifacts/kwin-build/RPMS/x86_64`. Later
builds may use other directories. Preserve the stock rollback RPMs too. The
installed custom package may not be downloadable from a Fedora repository.

## 2. Check the Fedora version you would update to

```sh
dnf --refresh --repo=fedora --repo=updates repoquery --available \
  --arch=x86_64 --latest-limit=1 \
  --queryformat '%{name}-%{version}-%{release}' kwin
```

This queries the stock Fedora repositories, not the installed custom package.
Record the exact result, including its release number and Fedora suffix. A change
from `6.8.2-3` to `6.8.2-4` also needs a new source review, even though the upstream
version is unchanged.

These commands describe the Fedora 44 setup. Following a Fedora release upgrade,
review the new distribution's source packages, build requirements and desktop
compatibility too.

## 3. Choose whether to update Fedora before rebuilding the patch

You can perform ordinary Fedora updates:

```sh
sudo dnf upgrade --refresh
```

If this replaces custom KWin with a stock package, log out and back in before
evaluating the result. PalmReject filtering should refuse to grab input when the
cancellation method is absent. The original trackpad remains available; custom
palm filtering is unavailable until the integration has been rebuilt and tested.

Alternatively, prepare the new custom package before changing KWin. Its build
dependencies may themselves require newer Qt or KDE libraries, so review the
dependency transaction rather than assuming it leaves the desktop unchanged.

Do not overwrite the installed compositor executable manually. There is no need
to freeze all desktop updates merely to keep the old patch installed.

## 4. Select the exact target and create separate work directories

The rest of this guide is the **maintainer procedure**. Keep the old working build
and rollback files intact while preparing the new one.

Replace the capitalized placeholders below with the values selected in step 2.
These are templates, not a claim that a particular newer release exists:

```sh
kwin_target_nvr='kwin-X.Y.Z-R.fc44'
kwin_custom_nvr='X.Y.Z-R.palmreject1.fc44'
kwin_source_dir="$PWD/artifacts/sources-${kwin_target_nvr}"
kwin_update_dir="$PWD/artifacts/build-${kwin_target_nvr}-palmreject1"
kwin_stock_dir="$PWD/artifacts/stock-${kwin_target_nvr}"
mkdir -p "$kwin_source_dir" "$kwin_stock_dir"
```

`kwin_target_nvr` includes the package name; `kwin_custom_nvr` is only the version
and release. Keep these shell variables in the same terminal for the following
commands. After opening a new terminal, define them again.

The build directory must not already exist. Use a new revision/directory for
another attempt if it contains a build you want to preserve. For changes to your
patch on the same Fedora base, increment the custom suffix, such as
`palmreject1` to `palmreject2`, so RPM can distinguish the builds.

## 5. Download and verify the new source and stock rollback RPMs

```sh
dnf download --srpm --destdir="$kwin_source_dir" "$kwin_target_nvr"
rpm --checksig "$kwin_source_dir/$kwin_target_nvr.src.rpm"
sha256sum "$kwin_source_dir/$kwin_target_nvr.src.rpm"
```

The Fedora source signature must verify. Record the SHA-256 only after verifying
the package's origin/signature. Do not replace the pinned hash merely to silence
a mismatch on an unverified file.

Also download the three stock runtime packages for this **new** base. Replace
`X.Y.Z-R.fc44` with the same target version/release:

```sh
dnf download --arch=x86_64 --destdir="$kwin_stock_dir" \
  kwin-X.Y.Z-R.fc44 kwin-common-X.Y.Z-R.fc44 kwin-libs-X.Y.Z-R.fc44
rpm --checksig "$kwin_stock_dir"/*.x86_64.rpm
```

Include any installed `kwin-devel` or `kwin-doc` subpackages in the backup/build
and eventual transaction as well. Stop if the exact matching source or rollback
packages are unavailable; do not quietly substitute a different release.

## 6. Review the new Fedora source before adapting the patch

In a separate scratch tree, import the new source RPM and apply Fedora's own
patches. Leave the custom build directory unused until its preparation recipe is
ready:

```sh
kwin_review_dir="$PWD/artifacts/review-${kwin_target_nvr}"
mkdir "$kwin_review_dir"
rpm -i --nodeps --define "_topdir $kwin_review_dir" \
  --define "_tmppath $kwin_review_dir" \
  "$kwin_source_dir/$kwin_target_nvr.src.rpm"
sudo dnf builddep "$kwin_review_dir/SPECS/kwin.spec"
rpmbuild -bp --nodeps --define "_topdir $kwin_review_dir" \
  --define "_tmppath $kwin_review_dir" "$kwin_review_dir/SPECS/kwin.spec"
```

`--nodeps` here permits source preparation; it is not permission to ignore missing
dependencies when compiling or installing binary packages.

Inspect the unpacked source under that directory's `BUILD/` tree. Its layout can
change with RPM or Fedora packaging, so find the actual KWin source directory
before applying commands there.

```sh
rg --files --no-ignore "$kwin_review_dir/BUILD" -g device.cpp | rg '/src/backends/libinput/device\.cpp$'
```

The source root is the part of that path before `/src/backends/libinput/device.cpp`.
Use it as the working directory for the patch dry run in step 7.

Review these points against the existing patch:

- The device-scoped `org.kde.KWin.InputDevice` interface and slot-export flags.
- The device identity checks and virtual-device detection.
- The input connection's thread, mutex and event-dispatch behavior.
- The queued compositor-thread reset and delayed D-Bus reply; no blocking wait on
  the input thread, and no access to destroyed devices/connections.
- Libinput's tapping reset behavior, especially pending taps, held buttons and
  drag lock. If libinput changed, inspect that version as well.
- The test mocks, libinput test target, CMake structure and Fedora spec.

If upstream already provides an equivalent cancellation operation, verify its
semantics and adapt the helper/tests instead of adding a duplicate interface.

## 7. Rebase the patch and update the preparation recipe

Adapt `packaging/kwin/0001-palmreject-cancel-tap-gestures.patch` against the new
Fedora-prepared source. First try a **dry run** from the actual source directory,
using the absolute path to the patch in this checkout:

```sh
patch --dry-run -p1 --fuzz=0 -i /absolute/path/to/T2-PalmReject/packaging/kwin/0001-palmreject-cancel-tap-gestures.patch
```

If it fails, review the changed code and regenerate the patch. Do not force it,
drop failing hunks, or remove the cancellation tests. Even a clean patch
application still requires semantic review of threading and reset behavior.

Update `packaging/kwin/prepare.py` deliberately:

| Recipe item | Required change/check |
| --- | --- |
| `EXPECTED` | Set the verified new source RPM's SHA-256. |
| Source/version error text | Name the newly reviewed base. |
| Release-field match | Match the new Fedora spec's actual release declaration. |
| Custom release | Keep the Fedora base release and add the chosen `palmreject` revision. |
| Patch insertion | Use an unused patch number and a valid insertion point; retain Fedora patches. |
| CMake arguments | Enable the required unit tests and the patch's test-subtree option. |
| `%check` | Integrate with any existing check section; retain other Fedora checks rather than blindly inserting a second section. |
| Build requirements | Include the actual new test/development requirements. |
| Text replacements | Verify each intended edit happened exactly once; changed spec formatting must not silently omit an edit. |

For example, a reviewed stock `6.8.3-1.fc44` base might become
`6.8.3-1.palmreject1.fc44`. That is an illustration, not a version to install
without checking availability. A same-base patch revision would use
`palmreject2` and a matching new build directory.

This is source maintenance, not an automatic command supplied by the current
script. If you do not maintain C++/Fedora packaging, have the maintainer complete
steps 6–7 before proceeding.

## 8. Prepare, inspect and build the new custom package

Once the script and patch target the new reviewed base:

```sh
python3 packaging/kwin/prepare.py \
  "$kwin_source_dir/$kwin_target_nvr.src.rpm" "$kwin_update_dir"
```

Inspect the generated spec and source RPM. Confirm its custom release matches
`kwin_custom_nvr`, that all Fedora patches remain, and that the test stage is
present. Then install its build requirements:

```sh
sudo dnf builddep "$kwin_update_dir/SPECS/kwin.spec"
```

Build the new directory directly; the convenience wrapper still points to
`artifacts/kwin-build`:

```sh
set -o pipefail
rpmbuild -ba --define "_topdir $kwin_update_dir" \
  --define "_tmppath $kwin_update_dir" \
  --define '_smp_build_ncpus 4' \
  "$kwin_update_dir/SPECS/kwin.spec" 2>&1 | tee "$kwin_update_dir/build.log"
```

Do not use `sudo rpmbuild`, `--nocheck`, or dependency-bypass flags to obtain an
apparently successful binary build.

## 9. Validate before installation

Require a successful build and passing unit tests. The old baseline had 307
device-test cases; the count can change upstream. The requirements are that the
intended tests actually ran, the cancellation regression remains covered, and
there are no unexplained failures or skipped required cases.

Use the persistent `build.log` captured in step 8. RPM may remove its temporary
`BUILD/` tree, including CTest's `LastTest.log`, after successful packaging. A
missing temporary log does not itself mean the tests failed.

Review the source patch and generated RPMs for:

- Tap preferences preserved; rejected contacts cannot become new tap-clicks.
- Pending tap and active drag/drag-lock cancellation, including the no-contact
  drag-lock state. A delayed reply acknowledges completed cancellation.
- Startup without the interface, helper failure, timeout and compositor exit.
- Matching runtime package versions, expected dependencies, file capabilities,
  payload paths and scriptlets. Build-ID paths normally change on rebuild.

Verify digests and preview the exact three runtime files:

```sh
rpm --checksig "$kwin_update_dir/RPMS/x86_64/kwin-${kwin_custom_nvr}.x86_64.rpm" \
  "$kwin_update_dir/RPMS/x86_64/kwin-common-${kwin_custom_nvr}.x86_64.rpm" \
  "$kwin_update_dir/RPMS/x86_64/kwin-libs-${kwin_custom_nvr}.x86_64.rpm"
dnf --assumeno install \
  "$kwin_update_dir/RPMS/x86_64/kwin-${kwin_custom_nvr}.x86_64.rpm" \
  "$kwin_update_dir/RPMS/x86_64/kwin-common-${kwin_custom_nvr}.x86_64.rpm" \
  "$kwin_update_dir/RPMS/x86_64/kwin-libs-${kwin_custom_nvr}.x86_64.rpm"
```

An abort from `--assumeno` is expected. Review the proposed changes, especially
when a newer KDE/Qt version is involved. Keep source hashes, the final patch/spec,
build and test logs, exact RPM hashes and rollback files together. An old
`validation.json` does not validate a new build.

## 10. Install, log in again, and repeat desktop acceptance

Stop any trial and save your work. Install the three reviewed runtime RPMs:

```sh
sudo systemctl stop palmreject.service
sudo systemctl stop palmreject-trial.service
sudo dnf install \
  "$kwin_update_dir/RPMS/x86_64/kwin-${kwin_custom_nvr}.x86_64.rpm" \
  "$kwin_update_dir/RPMS/x86_64/kwin-common-${kwin_custom_nvr}.x86_64.rpm" \
  "$kwin_update_dir/RPMS/x86_64/kwin-libs-${kwin_custom_nvr}.x86_64.rpm"
rpm -q kwin kwin-common kwin-libs libinput
```

Include matching installed development/documentation subpackages if applicable.
Log out and back in normally; do not replace the running compositor in place.

Repeat steps **9–10** of the [build/test/install guide](custom-kwin-build-test-install.md#9-build-palmreject-and-check-access-after-logging-in):
probe, passthrough, then filtered trials with USB recovery devices. Keep tapping
enabled and test both active dragging and drag lock with no fingers down. Check
that tapping resumes, the virtual device stays connected, settings remain
unchanged, and stop/expiry restores physical input.

Do not infer desktop acceptance from a unit-test pass or from an earlier KWin
version working. Record the new version's actual host results.

## 11. Roll back a failed custom update

Stop PalmReject first. Restore the **stock RPMs matching the new desktop base**
that you saved in step 5, together in one transaction, then log out and back in.
For a custom release with a `palmreject` suffix, its same-base stock release is a
downgrade. Replace the placeholders with that stock version:

```sh
sudo systemctl stop palmreject.service
sudo systemctl stop palmreject-trial.service
sudo dnf downgrade \
  /absolute/path/to/stock-directory/kwin-X.Y.Z-R.fc44.x86_64.rpm \
  /absolute/path/to/stock-directory/kwin-common-X.Y.Z-R.fc44.x86_64.rpm \
  /absolute/path/to/stock-directory/kwin-libs-X.Y.Z-R.fc44.x86_64.rpm
```

If the GUI cannot start, use a USB keyboard and `Ctrl+Alt+F3` (possibly also `Fn`)
to log in on a text console and run the rollback. Reboot if necessary afterward.

Returning to a previous custom build is a separate option only if it remains
compatible with the installed KDE/Qt stack. Do not blindly install the original
6.8.2 packages after a later desktop or Fedora release upgrade.

With stock KWin, leave custom filtering stopped until a compatible cancellation
integration is available. This update process does not create a boot service or
an automatic rebuild service. For permanent PalmReject operation, stop its
supervisor before package changes and refresh its rollback set after the update;
see [installation](palmreject.md#permanent-installation).
