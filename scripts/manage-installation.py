#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Install/remove root-owned PalmReject files; preserve calibration and recovery data."""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

STATE = '/var/lib/palmreject'
MANIFEST = STATE + '/install-manifest.json'
LIBEXEC = '/usr/local/libexec/palmreject'
UNIT = '/etc/systemd/system/palmreject.service'
PROFILE = '/etc/palmreject/profile.conf'
SETTINGS = '/etc/palmreject/settings.json'
UNINSTALL = '/usr/local/sbin/palmreject-uninstall'
FILES = {f'{LIBEXEC}/{name}' for name in ('palmreject', 'gesture-helper.py', 'service-manager.py',
                                        'manage-installation.py')} | {UNIT, PROFILE, SETTINGS, UNINSTALL}
RUNTIME_UNITS = ('palmreject.service', 'palmreject-input.service', 'palmreject-trial.service')
PACKAGES = ('kwin', 'kwin-common', 'kwin-libs', 'kwin-devel', 'kwin-doc')
QF = '%{NAME}|%{EPOCHNUM}|%{VERSION}|%{RELEASE}|%{ARCH}\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def execute(args, **kwargs):
    kwargs.setdefault('timeout', 120)
    kwargs.setdefault('check', True)
    return subprocess.run(args, text=True, **kwargs)


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f'Not a regular file: {path}')
        return stream.read()


def package_row(text):
    fields = text.strip().split('|')
    if len(fields) != 5 or any(not re.fullmatch(r'[A-Za-z0-9_.+~-]+', field) for field in fields):
        raise ValueError('Unexpected RPM metadata')
    return dict(zip(('name', 'epoch', 'version', 'release', 'arch'), fields))


def stock_row(installed):
    row = dict(installed)
    row['release'] = re.sub(r'\.palmreject[1-9][0-9]*(?=\.fc[0-9]+$)', '', row['release'])
    return row


def installed_packages(command=execute):
    packages = []
    for name in PACKAGES:
        try:
            row = package_row(command(['rpm', '-q', '--qf', QF, name], capture_output=True).stdout)
        except subprocess.CalledProcessError:
            if name in PACKAGES[:3]:
                raise ValueError(f'Required package not installed: {name}')
            continue
        packages.append(row)
    bases = {(p['epoch'], p['version'], stock_row(p)['release'], p['arch']) for p in packages}
    if len(bases) != 1:
        raise ValueError('KWin packages do not share the same desktop base/architecture')
    return packages


def verify_rpm(path, command=execute):
    result = command(['rpm', '--checksig', '--verbose', str(path)], capture_output=True).stdout
    if not re.search(r'signature[^\n]*: OK', result, re.I):
        raise ValueError(f'No verified RPM signature: {path}')
    return package_row(command(['rpm', '-qp', '--qf', QF, str(path)], capture_output=True).stdout)


def select_stock(directory, installed, command=execute):
    needed = {p['name']: stock_row(p) for p in installed}
    selected = {}
    for path in sorted(pathlib.Path(directory).glob('*.rpm')):
        row = package_row(command(['rpm', '-qp', '--qf', QF, str(path)], capture_output=True).stdout)
        if row == needed.get(row['name']):
            if row['name'] in selected:
                raise ValueError(f'Duplicate rollback RPM: {row["name"]}')
            verify_rpm(path, command)
            selected[row['name']] = (path, row)
    if set(selected) != set(needed):
        raise ValueError('Missing exact matching signed stock RPMs, including installed optional subpackages')
    return selected


class Installation:
    """Filesystem root/command injection is private and used by offline tests only."""
    def __init__(self, root=pathlib.Path('/'), command=execute):
        self.root = pathlib.Path(root)
        self.command = command

    def path(self, path):
        if not path.startswith('/') or '..' in pathlib.PurePosixPath(path).parts:
            raise ValueError('Unsafe installation path')
        result = self.root / path.lstrip('/')
        for parent in [*reversed(result.parents), result]:
            if parent == self.root or self.root in parent.parents:
                if parent.is_symlink():
                    # Fedora merges sbin into bin. Accept only this protected
                    # system alias, never a symlink at an installed file itself.
                    alias = (self.root == pathlib.Path('/') and parent == pathlib.Path('/usr/local/sbin')
                             and parent.resolve() == pathlib.Path('/usr/local/bin')
                             and parent.lstat().st_uid == 0)
                    if not alias:
                        raise ValueError(f'Refusing symlink: {parent}')
                if parent.exists() and self.root == pathlib.Path('/'):
                    st = parent.stat()
                    if st.st_uid != 0 or st.st_mode & 0o022:
                        raise ValueError(f'Not root-owned/protected: {parent}')
        return result

    def write(self, path, data, mode=0o600):
        target = self.path(path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        fd, temporary = tempfile.mkstemp(prefix='.palmreject-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, manifest):
        self.write(MANIFEST, (json.dumps(manifest, indent=2) + '\n').encode())

    def manifest(self):
        path = self.path(MANIFEST)
        if not path.exists():
            return None
        value = json.loads(read_regular(path))
        if value.get('schema') != 1 or set(value.get('files', {})) - FILES:
            raise ValueError('Unknown installation manifest; refusing to overwrite/remove')
        return value

    def conflicts(self, manifest):
        owned = (manifest or {}).get('files', {})
        for name in FILES:
            p = self.path(name)
            if p.exists() and (name not in owned or digest(read_regular(p)) != owned[name]['sha256']):
                raise ValueError(f'Existing/unexpectedly modified file; preserve and inspect: {name}')
        for directory in (UNIT + '.d',):
            if self.path(directory).exists():
                raise ValueError(f'Existing unmanaged unit overrides: {directory}')

    def install_files(self, payload, rollback, uid, old):
        self.conflicts(old)
        backup = STATE + f'/backups/{time.time_ns()}'
        transaction = {}
        for name in payload:
            path = self.path(name)
            transaction[name] = None
            if path.exists():
                saved = backup + name
                self.write(saved, read_regular(path), stat.S_IMODE(path.stat().st_mode))
                transaction[name] = saved
        records = {name: {'sha256': digest(data), 'mode': mode} for name, (data, mode) in payload.items()}
        manifest = {'schema': 1, 'phase': 'installing', 'session_uid': uid, 'files': records,
                    'rollback': [], 'transaction_backups': transaction}
        for name, (source, row) in rollback.items():
            data = read_regular(source)
            # Re-verify the root-owned copy; source files may change during staging.
            destination = STATE + '/rollback/' + pathlib.Path(source).name
            self.write(destination, data)
            if verify_rpm(self.path(destination), self.command) != row:
                raise ValueError('Rollback package changed during staging')
            manifest['rollback'].append({'path': destination, 'sha256': digest(data), 'package': row})
        self.save(manifest)  # Recovery record exists before installing executable files.
        try:
            for name, (data, mode) in payload.items():
                self.write(name, data, mode)
            manifest['phase'] = 'installed'
            self.save(manifest)
        except Exception:
            for name, saved in transaction.items():
                if saved:
                    p = self.path(saved)
                    self.write(name, read_regular(p), stat.S_IMODE(p.stat().st_mode))
                elif self.path(name).exists() and digest(read_regular(self.path(name))) == records[name]['sha256']:
                    self.path(name).unlink()
            if old:
                self.save(old)
            else:
                manifest.update(phase='install-failed', files={})
                self.save(manifest)
            raise
        return manifest

    def rollback_paths(self, manifest, installed):
        saved = manifest.get('rollback', [])
        current = {p['name']: stock_row(p) for p in installed}
        found = {}
        for item in saved:
            name = item['path']
            if not re.fullmatch(r'/var/lib/palmreject/rollback/[A-Za-z0-9_.+~-]+\.rpm', name):
                raise ValueError('Invalid rollback manifest path')
            p = self.path(name)
            if digest(read_regular(p)) != item['sha256']:
                raise ValueError(f'Rollback hash mismatch: {name}')
            row = verify_rpm(p, self.command)
            if row != item['package'] or row != current.get(row['name']):
                raise ValueError('Saved stock RPMs do not match the installed desktop; supply a reviewed updated rollback set')
            if row['name'] in found:
                raise ValueError('Duplicate rollback manifest entry')
            found[row['name']] = str(p)
        if set(found) != set(current):
            raise ValueError('Rollback set is incomplete for installed KWin subpackages')
        return list(found.values())

    def remove_files(self, manifest):
        preserved = []
        for name, record in manifest['files'].items():
            if name in (PROFILE, SETTINGS):
                continue
            path = self.path(name)
            if path.exists():
                if digest(read_regular(path)) == record['sha256']:
                    path.unlink()
                else:
                    preserved.append(name)
        manifest['phase'] = 'removed'
        manifest['preserved_modified_files'] = preserved
        self.save(manifest)
        return preserved


def payload(repository, config, uid):
    files = {}
    for name in ('palmreject', 'gesture-helper.py', 'service-manager.py', 'manage-installation.py'):
        source = repository / ('palmreject' if name == 'palmreject' else 'scripts/' + name)
        files[LIBEXEC + '/' + name] = (read_regular(source), 0o755)
    files[UNIT] = (read_regular(repository / 'systemd/palmreject.service'), 0o644)
    files[PROFILE] = (read_regular(config), 0o600)
    files[SETTINGS] = ((json.dumps({'session_uid': uid}) + '\n').encode(), 0o600)
    files[UNINSTALL] = (b'#!/bin/sh\nexec /usr/bin/python3 /usr/local/libexec/palmreject/manage-installation.py uninstall "$@"\n', 0o755)
    return files


def check_runtime_units(command=execute):
    owned = []
    for unit in ('palmreject-input.service', 'palmreject-trial.service'):
        result = command(['systemctl', 'show', unit, '-p', 'LoadState', '-p', 'Transient',
                          '-p', 'ExecStart', '-p', 'Description'], capture_output=True).stdout
        props = dict(line.split('=', 1) for line in result.splitlines() if '=' in line)
        if props.get('LoadState', 'not-found') == 'not-found':
            continue
        executable = props.get('ExecStart', '')
        identity = (f'path={LIBEXEC}/palmreject ;' in executable and
                    props.get('Description') == 'PalmReject restricted persistent input worker') if unit == 'palmreject-input.service' else bool(
                        re.search(r'path=/run/palmreject-trial\.[A-Za-z0-9]+/palmreject ;', executable))
        if props.get('Transient') != 'yes' or not identity:
            raise ValueError(f'Unmanaged {unit}; refusing to stop or replace it')
        owned.append(unit)
    return owned


def stop_all(command=execute):
    owned = check_runtime_units(command)
    state = command(['systemctl', 'show', 'palmreject.service', '-p', 'LoadState', '--value'],
                    capture_output=True).stdout.strip()
    if state != 'not-found':
        command(['systemctl', 'disable', '--now', 'palmreject.service'])
    for unit in owned:
        result = command(['systemctl', 'show', unit, '-p', 'LoadState', '--value'], capture_output=True).stdout.strip()
        if result == 'not-found':
            continue
        command(['systemctl', 'stop', unit])
        if unit == 'palmreject-input.service':
            command(['systemctl', 'revert', unit])
            command(['systemctl', 'reset-failed', unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    # A trial's owning launcher removes its unit/drop-ins asynchronously.
    deadline = time.monotonic() + 8
    while command(['systemctl', 'show', 'palmreject-trial.service', '-p', 'LoadState', '--value'],
                  capture_output=True).stdout.strip() != 'not-found':
        if time.monotonic() >= deadline:
            raise RuntimeError('Trial launcher cleanup incomplete; inspect before retrying')
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    install = sub.add_parser('install', help='Install and enable login/resume filtering')
    install.add_argument('--config', type=pathlib.Path, required=True)
    install.add_argument('--session-uid', type=int, default=int(os.environ.get('SUDO_UID', os.getuid())))
    install.add_argument('--stock-rpm-dir', type=pathlib.Path,
                         default=pathlib.Path(__file__).resolve().parents[1] / 'artifacts/kwin-stock')
    uninstall = sub.add_parser('uninstall', help='Disable/remove PalmReject and restore matching stock KWin')
    uninstall.add_argument('--keep-custom-kwin', action='store_true')
    for command in (install, uninstall):
        command.add_argument('--dry-run', action='store_true', help='Validate/print actions; do not write or change services/packages')
    args = parser.parse_args()
    if not args.dry_run and os.geteuid() != 0:
        parser.error('Run through sudo after building/testing as your ordinary user')
    instance = Installation()
    old = instance.manifest()
    if args.action == 'install':
        if args.session_uid <= 0:
            parser.error('Supply a nonroot --session-uid or invoke through sudo from that user')
        try:
            pwd.getpwuid(args.session_uid)
        except KeyError:
            parser.error('Configured session UID does not exist')
        repository = pathlib.Path(__file__).resolve().parents[1]
        for executable in ('systemctl', 'systemd-run', 'runuser', 'rpm', 'dnf', 'flock'):
            if not shutil.which(executable):
                raise ValueError(f'Missing dependency: {executable}')
        execute(['/usr/bin/python3', '-I', '-c', 'import dbus; from gi.repository import GLib'])
        execute([str(repository / 'palmreject'), '--check-config', str(args.config)], capture_output=True)
        packages = installed_packages()
        if not all(stock_row(p)['release'] != p['release'] for p in packages):
            raise ValueError('Install the matching custom KWin packages first; see the KWin guide')
        rollback = select_stock(args.stock_rpm_dir, packages)
        files = payload(repository, args.config, args.session_uid)
        instance.conflicts(old)
        print(f'Install {len(files)} root-owned files; configure UID {args.session_uid}; save signed stock RPMs; enable/start palmreject.service.', flush=True)
        if args.dry_run:
            print('Dry run: no files, services or packages changed.')
            return
        check_runtime_units()
        # No executable/configuration changes until all inputs have been validated.
        # A missing supervisor is expected on a first installation.
        state = execute(['systemctl', 'show', 'palmreject.service', '-p', 'LoadState', '--value'], capture_output=True).stdout.strip()
        if state != 'not-found' and not old:
            raise ValueError('An unmanaged PalmReject service already exists')
        if state != 'not-found':
            execute(['systemctl', 'stop', 'palmreject.service'])
        manifest = instance.install_files(files, rollback, args.session_uid, old)
        execute([LIBEXEC + '/palmreject', '--check-config', PROFILE], capture_output=True)
        if shutil.which('restorecon'):
            execute(['restorecon', '-R', LIBEXEC, '/etc/palmreject', UNIT, UNINSTALL, STATE])
        execute(['systemctl', 'daemon-reload'])
        # Stop the old trial only after the complete installation is ready.
        stop_all()
        try:
            execute(['systemctl', 'enable', '--now', 'palmreject.service'])
            deadline = time.monotonic() + 95
            while time.monotonic() < deadline:
                status = execute(['systemctl', 'show', 'palmreject.service', '-p', 'StatusText',
                                  '-p', 'ActiveState'], capture_output=True).stdout
                if 'StatusText=Filtering for session ' in status:
                    print('Persistent filtering is active; login and resume startup enabled.')
                    return
                if 'ActiveState=failed' in status or 'StatusText=Failed:' in status or 'StatusText=Stopped for this login' in status or 'StatusText=KWin/user bus not ready' in status:
                    raise RuntimeError('Persistent startup failed; inspect journalctl -u palmreject.service -u palmreject-input.service')
                time.sleep(0.5)
            # Installation outside an active graphical session is valid.
            print('Service enabled and waiting for an eligible Wayland session. Check status after login.')
        except Exception:
            execute(['systemctl', 'stop', 'palmreject.service'])
            manifest['phase'] = 'activation-failed'
            instance.save(manifest)
            raise
    else:
        if not old or old.get('phase') == 'removed':
            print('No active manifested installation; retained configuration/recovery files are unchanged.')
            return
        paths = []
        packages = []
        if not args.keep_custom_kwin:
            packages = installed_packages()
            paths = instance.rollback_paths(old, packages)
        print('Stop/disable PalmReject; remove manifested program/unit files; preserve profiles, records and RPMs.', flush=True)
        if paths:
            print('Restore verified matching stock KWin packages together; normal logout/login required.', flush=True)
        if args.dry_run:
            print('Dry run: no files, services or packages changed.')
            return
        stop_all()
        if paths and any(stock_row(p) != p for p in packages):
            # Keep program, manifest and standalone uninstaller if the transaction fails.
            execute(['dnf', '--assumeyes', '--disablerepo=*', 'downgrade', *paths], timeout=300)
            if installed_packages() != [stock_row(p) for p in packages]:
                raise RuntimeError('Stock package verification failed; installation retained for recovery')
        preserved = instance.remove_files(old)
        execute(['systemctl', 'daemon-reload'])
        print('PalmReject removed. Calibration and recovery data retained in /etc/palmreject and /var/lib/palmreject.')
        if paths:
            print('Log out and back in normally to use stock KWin. The running compositor was not restarted.')
        if preserved:
            print('Preserved modified installed files: ' + ', '.join(preserved))


if __name__ == '__main__':
    try:
        # Serialize installation/removal, independently of the runtime input lock.
        if '--dry-run' in sys.argv or '--help' in sys.argv or '-h' in sys.argv or os.geteuid() != 0:
            main()
        else:
            fd = os.open('/run/palmreject-install.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, 'w') as locked:
                fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
                main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'PalmReject: {error}', file=sys.stderr)
        sys.exit(1)
