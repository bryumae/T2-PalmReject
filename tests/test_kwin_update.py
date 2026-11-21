#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
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
                  patch.object(updater.installation, 'Installation') as instance,
                  patch.object(updater.installation, 'installed_packages', return_value=[row]),
                  patch.object(updater, 'download') as download):
                instance.return_value.manifest.return_value = manifest
                updater.update()
                download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
