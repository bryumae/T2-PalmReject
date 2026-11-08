"""Temporary-root installer tests with mocked RPM, DNF and systemd operations."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('installation', ROOT / 'scripts/manage-installation.py')
install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install)
CUSTOM = [dict(name=name, epoch='0', version='6.8.2', release='3.palmreject1.fc44', arch='x86_64') for name in install.PACKAGES[:3]]


class FakeCommands:
    def __init__(self):
        self.calls = []
        self.fail_dnf = False
        self.installed = CUSTOM
    def __call__(self, args, **kwargs):
        self.calls.append(args)
        output = ''
        if args[:3] == ['rpm', '-qp', '--qf']:
            output = pathlib.Path(args[-1]).read_text()
        elif args[:2] == ['rpm', '--checksig']:
            output = 'Header OpenPGP signature: OK\nPayload SHA256 digest: OK\n'
        elif args[0] == 'dnf':
            if self.fail_dnf:
                raise subprocess.CalledProcessError(1, args)
            self.installed = [install.stock_row(p) for p in self.installed]
        elif args[:2] == ['systemctl', 'show']:
            output = 'not-found\n'
        return subprocess.CompletedProcess(args, 0, output, '')


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.commands = FakeCommands()
        self.instance = install.Installation(self.root, self.commands)
        self.payload = {name: (('original ' + name).encode(), 0o755 if name.startswith(install.LIBEXEC) else 0o600)
                        for name in install.FILES}
        source = self.root / 'input-rpms'
        source.mkdir()
        self.rollback = {}
        for p in CUSTOM:
            stock = install.stock_row(p)
            path = source / (p['name'] + '.rpm')
            path.write_text('|'.join(stock.values()) + '\n')
            self.rollback[p['name']] = path, stock
    def install(self, old=None, payload=None):
        return self.instance.install_files(payload or self.payload, self.rollback, 1000, old)
    def test_first_install_and_manifest(self):
        manifest = self.install()
        self.assertEqual(manifest['phase'], 'installed')
        self.assertEqual(set(manifest['files']), install.FILES)
        self.assertEqual(len(self.instance.rollback_paths(manifest, CUSTOM)), 3)
        self.assertEqual(self.instance.path(install.PROFILE).stat().st_mode & 0o777, 0o600)
    def test_existing_unmanaged_files_and_symlinks_refused(self):
        self.instance.write(install.UNIT, b'other unit')
        with self.assertRaises(ValueError):
            self.install()
        self.instance.path(install.UNIT).unlink()
        self.instance.path(install.UNIT).symlink_to('/tmp/unknown')
        with self.assertRaises(ValueError):
            self.install()
    def test_upgrade_preserves_backups_and_refreshes_manifest(self):
        old = self.install()
        payload = dict(self.payload)
        payload[install.LIBEXEC + '/palmreject'] = b'new binary', 0o755
        updated = self.install(old, payload)
        saved = updated['transaction_backups'][install.LIBEXEC + '/palmreject']
        self.assertEqual(install.read_regular(self.instance.path(saved)), self.payload[install.LIBEXEC + '/palmreject'][0])
        self.assertEqual(install.read_regular(self.instance.path(install.LIBEXEC + '/palmreject')), b'new binary')
    def test_interrupted_copy_rolls_back_previous_files(self):
        old = self.install()
        payload = dict(self.payload)
        payload[install.LIBEXEC + '/palmreject'] = b'new binary', 0o755
        write = self.instance.write
        failed = False
        def fail_once(name, data, mode=0o600):
            nonlocal failed
            if name == install.UNIT and not failed:
                failed = True
                raise OSError('injected copy failure')
            return write(name, data, mode)
        with patch.object(self.instance, 'write', side_effect=fail_once), self.assertRaises(OSError):
            self.install(old, payload)
        for name, (data, mode) in self.payload.items():
            self.assertEqual(install.read_regular(self.instance.path(name)), data)
        self.assertEqual(self.instance.manifest(), old)
    def test_remove_preserves_config_artifacts_and_modified_files(self):
        manifest = self.install()
        modified = install.LIBEXEC + '/gesture-helper.py'
        self.instance.write(modified, b'user modifications')
        artifact = self.root / 'artifacts/recovery.rpm'
        artifact.parent.mkdir()
        artifact.write_bytes(b'keep')
        self.assertEqual(self.instance.remove_files(manifest), [modified])
        for name in (install.PROFILE, install.SETTINGS, modified):
            self.assertTrue(self.instance.path(name).exists())
        self.assertFalse(self.instance.path(install.UNIT).exists())
        self.assertTrue(artifact.exists())
        self.assertTrue(self.instance.path(manifest['rollback'][0]['path']).exists())
    def test_hash_or_desktop_version_mismatch_refuses_rollback(self):
        manifest = self.install()
        changed = [dict(p, version='6.9.0') for p in CUSTOM]
        with self.assertRaises(ValueError):
            self.instance.rollback_paths(manifest, changed)
        self.instance.path(manifest['rollback'][0]['path']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            self.instance.rollback_paths(manifest, CUSTOM)
    def test_unsigned_and_missing_optional_stock_packages_refused(self):
        def unsigned(args, **kwargs):
            if args[:2] == ['rpm', '--checksig']:
                return subprocess.CompletedProcess(args, 0, 'digests OK')
            return self.commands(args, **kwargs)
        with self.assertRaises(ValueError):
            install.select_stock(self.root / 'input-rpms', CUSTOM, unsigned)
        optional = CUSTOM + [dict(CUSTOM[0], name='kwin-devel')]
        with self.assertRaises(ValueError):
            install.select_stock(self.root / 'input-rpms', optional, self.commands)
    def invoke(self, argv):
        # All filesystem/service/package interaction below is injected/mocked.
        with patch.object(sys, 'argv', ['manage-installation.py', *argv]), \
             patch.object(install, 'Installation', return_value=self.instance), \
             patch.object(install, 'execute', side_effect=self.commands), \
             patch.object(install, 'installed_packages', side_effect=lambda: self.commands.installed), \
             patch.object(install, 'select_stock', return_value=self.rollback), \
             patch.object(install, 'payload', return_value=self.payload), \
             patch.object(install, 'stop_all') as stop, \
             patch.object(install.os, 'geteuid', return_value=0):
            install.main()
            return stop.call_count
    def test_dry_run_performs_no_writes_or_service_actions(self):
        self.assertEqual(self.invoke(['install', '--dry-run', '--config', '/unused', '--session-uid', '1000']), 0)
        self.assertFalse(self.instance.path(install.MANIFEST).exists())
        self.install()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.invoke(['uninstall', '--dry-run']), 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertFalse(any(c[0] in ('systemctl', 'dnf') for c in self.commands.calls))
    def test_dnf_failure_leaves_recovery_tools_and_manifest(self):
        manifest = self.install()
        self.commands.fail_dnf = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.invoke(['uninstall'])
        self.assertTrue(self.instance.path(install.UNINSTALL).exists())
        self.assertEqual(self.instance.manifest(), manifest)
    def test_default_uninstall_restores_stock_without_killing_kwin(self):
        self.install()
        self.assertEqual(self.invoke(['uninstall']), 1)
        self.assertEqual(self.commands.installed, [install.stock_row(p) for p in CUSTOM])
        dnf = next(c for c in self.commands.calls if c[0] == 'dnf')
        self.assertIn('--disablerepo=*', dnf)
        self.assertEqual(len([p for p in dnf if p.endswith('.rpm')]), 3)
        self.assertFalse(any(c[0] in ('kill', 'pkill', 'loginctl') for c in self.commands.calls))
        self.assertEqual(self.instance.manifest()['phase'], 'removed')
    def test_palmreject_only_uninstall_skips_dnf(self):
        self.install()
        self.invoke(['uninstall', '--keep-custom-kwin'])
        self.assertFalse(any(c[0] == 'dnf' for c in self.commands.calls))
    def test_manifest_cannot_remove_arbitrary_paths(self):
        self.instance.write(install.MANIFEST, json.dumps({'schema': 1, 'files': {'/etc/passwd': {}}}).encode())
        with self.assertRaises(ValueError):
            self.instance.manifest()


if __name__ == '__main__':
    unittest.main()
