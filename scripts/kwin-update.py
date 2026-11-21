#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Replace a stock Fedora KWin build with the verified PalmReject build."""
import fcntl
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import re
import subprocess
import sys

# systemd invokes Python in isolated mode. Load only our root-owned sibling.
module = importlib.util.spec_from_file_location(
    'installation', Path(__file__).resolve().with_name('manage-installation.py'))
installation = importlib.util.module_from_spec(module)
module.loader.exec_module(installation)

RUN = Path('/run/palmreject-kwin-update')
CACHE = Path(installation.BUILD_CACHE)
RECIPE = Path(installation.LIBEXEC) / 'kwin'
FAILED = installation.STATE + '/kwin-update-rejected.json'
TIMER = 'palmreject-kwin-update.timer'
BUILDER = 'palmreject-kwin-build.service'
FEDORA_KEY = '/etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-44-primary'
execute = installation.execute


def rpm_query(path, *options):
    return execute(['rpm', '-qp', *options, str(path)], capture_output=True).stdout


def package(path):
    return installation.package_row(rpm_query(path, '--qf', installation.QF))


def spec_for(row):
    return '{name}-{epoch}:{version}-{release}.{arch}'.format(**row)


def patched(row):
    return dict(row, release=row['release'].replace('.fc44', '.palmreject1.fc44'))


def check_platform(rows):
    system = platform.freedesktop_os_release()
    if (system.get('ID'), system.get('VERSION_ID'), os.uname().machine) != ('fedora', '44', 'x86_64'):
        raise ValueError('Automatic KWin updates support Fedora 44 x86_64')
    if rows[0]['arch'] != 'x86_64':
        raise ValueError('Automatic KWin updates require x86_64 KWin packages')
    if any(not re.fullmatch(r'[0-9]+\.fc44', row['release']) or row['epoch'] != '0'
           or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', row['version']) for row in rows):
        raise ValueError('Unsupported stock Fedora KWin version or release')


def enabled():
    return execute(['systemctl', 'is-enabled', '--quiet', TIMER], check=False).returncode == 0


def check_fedora_signature(path, keydb):
    output = execute(['rpmkeys', '--dbpath', str(keydb), '--checksig', '--verbose', str(path)],
                     capture_output=True).stdout
    if not re.search(r'signature[^\n]*: OK', output, re.I):
        raise ValueError(f'Fedora signature missing: {path.name}')


def download(inputs, rows):
    version, release = rows[0]['version'], rows[0]['release']
    source = inputs / f'kwin-{version}-{release}.src.rpm'
    cmd = ['dnf5', '--disable-plugin=*']
    execute([*cmd, 'download', '--srpm', '--repo=fedora-source', '--repo=updates-source',
             f'--destdir={inputs}', f'kwin-{version}-{release}'], timeout=600)
    execute([*cmd, 'download', '--repo=fedora', '--repo=updates', f'--destdir={inputs}',
             *map(spec_for, rows)], timeout=600)
    keydb = RUN / 'keys'
    keydb.mkdir(mode=0o700)
    execute(['rpmkeys', '--dbpath', str(keydb), '--import', FEDORA_KEY])
    check_fedora_signature(source, keydb)
    if (rpm_query(source, '--qf', '%{SOURCEPACKAGE}|%{NAME}|%{EPOCHNUM}|%{VERSION}|%{RELEASE}')
            != f'1|kwin|0|{version}|{release}'):
        raise ValueError('Source RPM does not match installed KWin')
    stock = installation.select_stock(inputs, rows)
    for path, _ in stock.values():
        check_fedora_signature(path, keydb)
        if rpm_query(path, '--qf', '%{SOURCERPM}') != source.name:
            raise ValueError(f'Stock RPM has a different source build: {path.name}')
    # The builder only receives the signed source, with a fixed filename.
    source.chmod(0o644)
    return source, stock


def package_shape(path, custom_release=None, stock_release=None):
    def normalized(option):
        lines = rpm_query(path, option).splitlines()
        if custom_release:
            lines = [line.replace(custom_release, stock_release) for line in lines]
        if option == '--filecaps':
            lines = [line for line in lines if not line.startswith('/usr/lib/.build-id')]
        if option in ('--scripts', '--triggers', '--filetriggers'):
            return lines
        return sorted(lines)

    return {option: normalized(option) for option in
            ('--requires', '--provides', '--conflicts', '--obsoletes', '--filecaps',
             '--scripts', '--triggers', '--filetriggers')}


def candidates(output, stock, dest):
    packages = {}
    for name, (original, row) in stock.items():
        expected = patched(row)
        filename = '{name}-{version}-{release}.{arch}.rpm'.format(**expected)
        source = output / expected['arch'] / filename
        if not source.is_file() or source.resolve() != source:
            raise ValueError(f'Missing or unsafe built RPM: {filename}')
        target = dest / filename
        target.write_bytes(installation.read_regular(source))
        if package(target) != expected:
            raise ValueError(f'Unexpected build metadata: {filename}')
        execute(['rpmkeys', '--checksig', str(target)])
        stock_shape = package_shape(original)
        new_shape = package_shape(target, expected['release'], row['release'])
        changed = [option for option in stock_shape if stock_shape[option] != new_shape[option]]
        if changed:
            raise ValueError(f'Build differs from stock package interfaces: {filename} ({", ".join(changed)})')
        packages[name] = target
    return packages


def resolve_replacement(base, rows, paths, dnf):
    repo = base.get_repo_sack()
    repo.load_repos(dnf.repo.Repo.Type_SYSTEM)
    goal = dnf.base.Goal(base)
    for path in paths.values():
        goal.add_install(str(path))
    transaction = goal.resolve()
    if transaction.get_problems():
        raise RuntimeError('; '.join(transaction.get_resolve_logs_as_strings()))
    validate_transaction(transaction, rows, dnf.transaction)
    return transaction


def rpmdb_snapshot():
    rows = execute(['rpm', '-qa', '--qf', installation.QF], capture_output=True).stdout
    return hashlib.sha256(''.join(sorted(rows.splitlines(keepends=True))).encode()).digest()


def install_rpms(rows, paths, instance, manifest, stock, snapshot):
    import libdnf5 as dnf

    base = dnf.base.Base()
    base.load_config()
    cfg = base.get_config()
    cfg.get_plugins_option().set(False)
    # These locally built, root-staged packages have digest and metadata checks.
    cfg.get_localpkg_gpgcheck_option().set(False)
    base.setup()
    if not base.lock_system_repo(dnf.utils.LockAccess_WRITE, dnf.utils.LockBlocking_NON_BLOCKING):
        raise RuntimeError('Another package manager is active; will retry')
    if installation.installed_packages() != rows or rpmdb_snapshot() != snapshot or not enabled():
        print('Installed packages changed or updater disabled; discarding stale build', flush=True)
        return
    transaction = resolve_replacement(base, rows, paths, dnf)

    # Record recovery packages first. Their base also matches the still-installed stock.
    recovery = instance.stage_rollback(stock)
    manifest['rollback'] = recovery
    instance.save(manifest)
    transaction.set_description('PalmReject: install tested KWin for installed Fedora release')
    result = transaction.run()
    if result != transaction.TransactionRunResult_SUCCESS:
        details = [transaction.transaction_result_to_string(result),
                   *transaction.get_transaction_problems(), *transaction.get_rpm_messages()]
        raise RuntimeError('; '.join(str(detail) for detail in details if detail))
    if installation.installed_packages() != [patched(row) for row in rows]:
        raise RuntimeError('Installed KWin package set did not match the tested build')
    print('Patched KWin installed. Log out and back into KDE to activate PalmReject.', flush=True)


def validate_transaction(transaction, rows, actions):
    def identity(pkg):
        return (pkg.get_name(), str(pkg.get_epoch()), pkg.get_version(),
                pkg.get_release(), pkg.get_arch())

    def row_identity(row):
        return tuple(row[key] for key in ('name', 'epoch', 'version', 'release', 'arch'))

    expected = [(actions.TransactionItemAction_UPGRADE, row_identity(patched(r))) for r in rows]
    expected += [(actions.TransactionItemAction_REPLACED, row_identity(r)) for r in rows]
    actual = [(item.get_action(), identity(item.get_package()))
              for item in transaction.get_transaction_packages()]
    if sorted(actual) != sorted(expected):
        raise ValueError('Transaction would change packages outside the exact KWin replacement')


def update():
    instance = installation.Installation()
    manifest = instance.manifest()
    if not manifest or installation.UPDATE_TIMER not in manifest['files'] or not enabled():
        return
    rows = installation.installed_packages()
    already = [row != installation.stock_row(row) for row in rows]
    if all(already):
        return
    if any(already):
        raise ValueError('Mixed stock and custom KWin packages; restore a consistent set')
    check_platform(rows)
    ident = {'packages': rows, 'builder': installation.digest(installation.read_regular(
        Path('/etc/systemd/system') / BUILDER)), 'recipe': {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(RECIPE.iterdir())
        if p.suffix in ('.py', '.patch', '.json')
    }}
    failed = instance.path(FAILED)
    retry = instance.path(installation.STATE + '/kwin-update-retry')
    if retry.exists():
        retry.unlink()
        failed.unlink(missing_ok=True)
    if failed.exists() and json.loads(installation.read_regular(failed)) == ident:
        print(f'Skipping previously rejected KWin build. Inspect journalctl -u {BUILDER} and request a retry after correcting it.', flush=True)
        return

    inputs = RUN / 'download'
    inputs.mkdir(mode=0o700)
    verified = RUN / 'verified'
    verified.mkdir()
    verified.chmod(0o755)  # Traversable by the build user despite UMask=0077.
    source, stock = download(inputs, rows)
    # Keep a stable root-owned input path. DNF's cache is never mounted into the builder.
    source.rename(verified / 'kwin.src.rpm')

    # The build service has stopped before its output is inspected or removed.
    snapshot = rpmdb_snapshot()
    result = execute(['systemctl', 'start', BUILDER], timeout=14460, check=False)
    real_cache = CACHE.resolve()
    if real_cache != CACHE:
        raise ValueError('Unexpected systemd build cache path')
    if installation.installed_packages() != rows or rpmdb_snapshot() != snapshot:
        print('Installed packages changed during the build; discarding stale build', flush=True)
        return
    if result.returncode:
        instance.write(FAILED, json.dumps(ident).encode())
        raise RuntimeError(f'KWin build failed; see journalctl -u {BUILDER}. '
                           'Review the failure, then request a manual retry.')
    destination = RUN / 'packages'
    destination.mkdir(mode=0o700)
    try:
        paths = candidates(real_cache / 'work/RPMS', stock, destination)
    except (ValueError, subprocess.CalledProcessError):
        instance.write(FAILED, json.dumps(ident).encode())
        raise
    lock = os.open('/run/palmreject-install.lock', os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_WRONLY, 0o600)
    with os.fdopen(lock, 'w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if instance.manifest() != manifest:
            raise RuntimeError('PalmReject installation changed during the build; will retry')
        install_rpms(rows, paths, instance, manifest, stock, snapshot)
        failed.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        update()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'PalmReject KWin update: {error}', file=sys.stderr)
        sys.exit(1)
