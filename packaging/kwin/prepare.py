#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Prepare a pinned Fedora KWin source RPM; never install or replace KWin."""
import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess

EXPECTED = "9f70a200139689b206b6d387433be4c346210b40e49d0a7f226b8ce674b6cfbb"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_rpm", type=pathlib.Path)
    parser.add_argument("workdir", type=pathlib.Path, help="A new, unprivileged build directory")
    args = parser.parse_args()
    source = args.source_rpm.resolve(strict=True)
    if hashlib.sha256(source.read_bytes()).hexdigest() != EXPECTED:
        parser.error("Source RPM differs from the reviewed kwin-6.8.2-3.fc44 source")
    subprocess.run(["rpm", "--checksig", str(source)], check=True)
    work = args.workdir.resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    definitions = ["--define", f"_topdir {work}", "--define", f"_tmppath {work}"]
    subprocess.run(["rpm", "-i", "--nodeps", *definitions, str(source)], check=True)
    spec = work / "SPECS/kwin.spec"
    text = spec.read_text()
    text, n = re.subn(r"^Release: 3%\{\?dist\}$", "Release: 3.palmreject1%{?dist}", text, flags=re.M)
    if n != 1:
        raise RuntimeError("Unexpected Fedora release field")
    patch = pathlib.Path(__file__).resolve().with_name("0001-palmreject-cancel-tap-gestures.patch")
    shutil.copyfile(patch, work / "SOURCES" / patch.name)
    text = text.replace("## proposed patches", f"Patch100: {patch.name}\n\n## proposed patches", 1)
    text = text.replace("%cmake_kf6\n", "%cmake_kf6 -DBUILD_TESTING=ON -DKWIN_BUILD_PALMREJECT_TESTS_ONLY=ON\n", 1)
    text = text.replace("%install\n", """%check
QT_QPA_PLATFORM=offscreen dbus-run-session -- ctest --test-dir %{_vpath_builddir} -R '^kwin-testLibinputDevice$' --no-tests=error --output-on-failure

%install
""", 1)
    text = text.replace("# Base\n", "# Base\nBuildRequires: dbus-daemon\nBuildRequires: cmake(Qt6WaylandClientPrivate)\n", 1)
    spec.write_text(text)
    subprocess.run(["rpmbuild", "-bs", "--nodeps", *definitions, str(spec)], check=True)
    print(f"Prepared {spec}")
    print("Install build dependencies with sudo dnf builddep SPEC, then build unprivileged:")
    print(f"rpmbuild -ba --define '_topdir {work}' --define '_tmppath {work}' {spec}")


if __name__ == "__main__":
    main()
