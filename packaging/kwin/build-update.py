#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build a verified stock SRPM with the reviewed PalmReject patch, as a nonroot user."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


RECIPE = Path(__file__).resolve().parent
PATCH = '0001-palmreject-cancel-tap-gestures.patch'


def replace_once(text, pattern, replacement):
    text, count = re.subn(pattern, replacement, text, flags=re.M)
    if count != 1:
        raise ValueError(f'Unreviewed Fedora spec layout: {pattern}')
    return text


def custom_spec(text, patch_name=PATCH):
    if re.search(r'^%check\b|^[ \t]*Source100\s*:', text, re.M | re.I):
        raise ValueError('Fedora spec already defines %check or Source100; review required')
    text = replace_once(text, r'^Release:[ \t]+([0-9]+)%\{\?dist\}$',
                        r'Release: \1.palmreject1%{?dist}')
    text = replace_once(text, r'^## proposed patches$', f'Source100: {patch_name}\n\n## proposed patches')
    text = replace_once(text, r'^# Base$', '# Base\nBuildRequires: dbus-daemon\n'
                        'BuildRequires: cmake(Qt6WaylandClientPrivate)')
    # Leave Fedora's patch sequence intact, then apply the separately declared patch.
    text = replace_once(text, r'^%autosetup -p1$', '%autosetup -p1\n'
                        'patch --batch --forward --fuzz=0 -p1 -i %{SOURCE100}')
    text = replace_once(text, r'^%cmake_kf6$', '%cmake_kf6 -DBUILD_TESTING=ON '
                        '-DKWIN_BUILD_PALMREJECT_TESTS_ONLY=ON')
    return replace_once(text, r'^%install$', "%check\n"
                        "QT_QPA_PLATFORM=offscreen dbus-run-session -- ctest --test-dir "
                        "%{_vpath_builddir} -R '^kwin-testLibinputDevice$' --no-tests=error "
                        "--verbose --output-log palmreject-ctest.log\n"
                        "grep -F 'PASS   : TestLibinputDevice::testResetTapGestures()' palmreject-ctest.log\n"
                        "%install")


def run(*args):
    subprocess.run(args, check=True)


def prepare(source, work):
    nvr = subprocess.check_output(
        ['rpm', '-qp', '--qf', '%{SOURCEPACKAGE}|%{NAME}|%{EPOCHNUM}|%{RELEASE}', str(source)],
        text=True)
    match = re.fullmatch(r'1\|kwin\|0\|[0-9]+\.fc(44|45)', nvr)
    if not match:
        raise ValueError('Unsupported KWin source RPM release')
    release = match[1]
    dist = subprocess.check_output(['rpm', '--eval', '%{?dist}'], text=True).strip()
    if dist != f'.fc{release}':
        raise ValueError('KWin source RPM does not match the builder Fedora release')
    patch_name = PATCH if release == '44' else PATCH.replace('.patch', '.fc45.patch')
    review_name = 'reviewed-input.json' if release == '44' else 'reviewed-input.fc45.json'
    work.mkdir(mode=0o700)
    opt = ('--define', f'_topdir {work}', '--define', f'_tmppath {work}')
    run('rpm', '-i', '--nodeps', *opt, str(source))
    spec = work / 'SPECS/kwin.spec'
    original = spec.read_text()
    transformed = custom_spec(original, patch_name)
    run('rpmbuild', '-bp', '--nodeps', *opt, str(spec))
    candidates = list((work / 'BUILD').glob('*/kwin-*/src/backends/libinput/device.cpp'))
    if len(candidates) != 1:
        raise ValueError('Could not locate the Fedora-prepared libinput sources')
    tree = candidates[0].parents[3]
    reviewed = json.loads((RECIPE / review_name).read_text())
    for name, accepted in reviewed.items():
        if hashlib.sha256((tree / name).read_bytes()).hexdigest() not in accepted:
            raise ValueError(f'Unreviewed KWin source in {name}; rebase and review required')
    run('patch', '--dry-run', '--batch', '--forward', '--fuzz=0',
        '-p1', '-d', str(tree), '-i', str(RECIPE / patch_name))
    shutil.copyfile(RECIPE / patch_name, work / 'SOURCES' / patch_name)
    spec.write_text(transformed)
    # Remove the stock prep tree so the real build runs %prep from scratch.
    shutil.rmtree(work / 'BUILD')
    return spec, opt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('work', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Use an unprivileged build user')
    spec, opt = prepare(args.source.resolve(), args.work.resolve())
    if not args.prepare_only:
        run('rpmbuild', '-bb', *opt, '--define', '_smp_build_ncpus 4', str(spec))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'KWin build: {error}', file=sys.stderr)
        sys.exit(1)
