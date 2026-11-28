#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


updater = load('updater', 'scripts/kwin-update.py')
builder = load('builder', 'packaging/kwin/build-update.py')
STOCK = {'name': 'kwin', 'epoch': '0', 'version': '6.8.3', 'release': '1.fc44', 'arch': 'x86_64'}
SPEC = '''Release: 1%{?dist}
## proposed patches
# Base
%autosetup -p1
%cmake_kf6
%install
'''


class UpdateTests(unittest.TestCase):
    def test_builder_rejects_cross_release_source_before_unpacking(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'work'
            with patch.object(builder.subprocess, 'check_output',
                              side_effect=['1|kwin|0|2.fc45', '.fc44']):
                with self.assertRaisesRegex(ValueError, 'does not match the builder'):
                    builder.prepare(Path('kwin.src.rpm'), work)
            self.assertFalse(work.exists())

    def test_stock_fedora45_invokes_builder_but_stale_result_is_discarded(self):
        stock = dict(STOCK, release='2.fc45')
        manifest = {'files': {updater.installation.UPDATE_TIMER: {}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'signed.src.rpm'
            source.touch()
            with (patch.object(updater, 'RUN', root), patch.object(updater, 'CACHE', root),
                  patch.object(updater, 'enabled', return_value=True),
                  patch.object(updater.installation, 'Installation') as factory,
                  patch.object(updater.installation, 'installed_packages', return_value=[stock]),
                  patch.object(updater.installation, 'kwin_update_release', return_value='45'),
                  patch.object(updater.installation, 'fedora_signing_key', return_value='fedora45-key'),
                  patch.object(updater.installation, 'read_regular', return_value=b'builder unit'),
                  patch.object(updater, 'download', return_value=(source, {})) as download,
                  patch.object(updater, 'rpmdb_snapshot', side_effect=[b'before', b'after']),
                  patch.object(updater, 'execute', return_value=SimpleNamespace(returncode=0)) as run,
                  patch.object(updater, 'install_rpms') as install):
                factory.return_value.manifest.return_value = manifest
                factory.return_value.path.side_effect = lambda name: root / Path(name).name
                updater.update()
                download.assert_called_once_with(root / 'download', [stock], 'fedora45-key')
                run.assert_called_once_with(['systemctl', 'start', updater.BUILDER],
                                            timeout=14460, check=False)
                install.assert_not_called()

    def test_platform_and_release_selection(self):
        stock45 = dict(STOCK, release='2.fc45')
        installer = updater.installation
        for version, stock in [('44', STOCK), ('45', stock45)]:
            with patch.object(installer.platform, 'freedesktop_os_release',
                              return_value={'ID': 'fedora', 'VERSION_ID': version}):
                self.assertEqual(installer.kwin_update_release([stock]), version)
                self.assertEqual(updater.patched(stock)['release'],
                                 stock['release'].replace('.fc', '.palmreject1.fc'))
                self.assertEqual(installer.kwin_update_release([updater.patched(stock)]), version)
                with self.assertRaises(ValueError):
                    installer.kwin_update_release([dict(stock, release='2.fc46')])
        with patch.object(installer.platform, 'freedesktop_os_release',
                          return_value={'ID': 'fedora', 'VERSION_ID': '46'}):
            with self.assertRaises(ValueError):
                installer.kwin_update_release([stock45])

    def test_fedora45_key_must_belong_to_fedora_gpg_keys(self):
        installer = updater.installation
        with (patch.object(Path, 'is_file', return_value=True),
              patch.object(Path, 'resolve', autospec=True, side_effect=lambda p: p),
              patch.object(installer, 'execute', return_value=SimpleNamespace(stdout='fedora-gpg-keys')) as rpm):
            key = installer.fedora_signing_key('45')
            self.assertEqual(str(key), '/usr/share/pki/rpm-gpg/RPM-GPG-KEY-fedora-45-primary')
            rpm.assert_called_once_with(['rpm', '-qf', '--qf', '%{NAME}', str(key)], capture_output=True)
            rpm.return_value.stdout = 'unrelated-package'
            with self.assertRaisesRegex(ValueError, 'fedora-gpg-keys'):
                installer.fedora_signing_key('45')

    def test_unreviewed_spec_fails_closed(self):
        result = builder.custom_spec(SPEC)
        self.assertIn('Release: 1.palmreject1%{?dist}', result)
        self.assertIn('--fuzz=0', result)
        self.assertIn('%autosetup -p1\npatch ', result)
        self.assertIn('Patch100: fedora.patch', builder.custom_spec(SPEC + 'Patch100: fedora.patch\n'))
        self.assertIn('kwin-testLibinputDevice', result)
        for malformed in (SPEC + '%check\n', SPEC + 'Source100: other.tar\n',
                          SPEC.replace('%autosetup -p1', '%setup -q'),
                          SPEC.replace('%cmake_kf6', '%cmake_kf6 --new-options')):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                builder.custom_spec(malformed)

    def test_transaction_requires_the_exact_old_and_new_packages(self):
        ns = SimpleNamespace(TransactionItemAction_UPGRADE=1, TransactionItemAction_REPLACED=2)
        transaction = Mock()

        def item(action, row):
            return SimpleNamespace(
                get_action=lambda: action,
                get_package=lambda: SimpleNamespace(**{
                    'get_' + key: lambda v=value: v for key, value in row.items()
                }))

        old = item(2, STOCK)
        new = item(1, updater.patched(STOCK))
        transaction.get_transaction_packages.return_value = [old, new]
        updater.validate_transaction(transaction, [STOCK], ns)
        for invalid in ([new], [old, new, item(1, dict(STOCK, name='qt6-qtbase'))],
                        [new, item(2, dict(STOCK, version='6.8.4'))]):
            transaction.get_transaction_packages.return_value = invalid
            with self.assertRaises(ValueError):
                updater.validate_transaction(transaction, [STOCK], ns)

    def test_disabled_or_already_patched_does_not_download(self):
        manifest = {'files': {updater.installation.UPDATE_TIMER: {}}}
        for enabled, row in ((False, STOCK), (True, updater.patched(STOCK))):
            with (patch.object(updater, 'enabled', return_value=enabled),
                  patch.object(updater.installation, 'kwin_update_release', return_value='44'),
                  patch.object(updater.installation, 'Installation') as instance,
                  patch.object(updater.installation, 'installed_packages', return_value=[row]),
                  patch.object(updater, 'download') as download):
                instance.return_value.manifest.return_value = manifest
                updater.update()
                download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
