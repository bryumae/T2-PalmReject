"""Offline CLI checks: reject unsafe invocation before attempting device access."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CLI(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([str(ROOT / 'palmreject'), *args], capture_output=True, text=True)

    def test_requires_explicit_single_mode(self):
        for args in [(), ('--probe', '--observe'), ('--unknown',), ('--device',),
                     ('--probe', '--device', '/dev/null', '--device', '/dev/null')]:
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode, 2)

    def test_live_modes_require_supervision_and_profile(self):
        for args in [('--filter',), ('--passthrough',),
                     ('--filter', '--config', '/no-such-file'),
                     ('--passthrough', '--config', '/no-such-file')]:
            self.assertEqual(self.run_cli(*args).returncode, 2)

    def test_help_opens_no_device(self):
        result = self.run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--observe', result.stdout)

    def test_wrong_character_device_rejected(self):
        self.assertEqual(self.run_cli('--probe', '--device', '/dev/null').returncode, 1)

    def test_duration_validation(self):
        for value in ('', '0', '01', '-1', '+60', '1.5', '86401', '999999999999', '60s'):
            with self.subTest(value=value):
                self.assertEqual(self.run_cli('--passthrough', '--duration', value).returncode, 2)
                result = subprocess.run(['bash', str(ROOT / 'scripts/trial.sh'),
                                         '--passthrough', '--duration', value], capture_output=True)
                self.assertEqual(result.returncode, 2)
        for value in ('1', '3600', '86400'):
            self.assertEqual(self.run_cli('--passthrough', '--state-dir', '/tmp',
                                         '--device', '/dev/null', '--duration', value).returncode, 1)
        self.assertEqual(self.run_cli('--observe', '--duration', '3600').returncode, 2)
        self.assertEqual(self.run_cli('--passthrough', '--duration', '60',
                                     '--duration', '3600').returncode, 2)

    def test_session_uid_is_restricted_to_filtering(self):
        for uid in ('0', '-1', '+1000', '1000x', '999999999999999999999999999'):
            with self.subTest(uid=uid):
                self.assertEqual(self.run_cli('--filter', '--config', '/no-such-file',
                                             '--session-uid', uid).returncode, 2)
        self.assertEqual(self.run_cli('--probe', '--session-uid', '1000').returncode, 2)

    def test_shell_syntax(self):
        for file in ['install.sh', 'uninstall.sh', 'scripts/trial.sh', 'scripts/detect-trackpad.sh',
                     'scripts/build-kwin.sh']:
            subprocess.run(['bash', '-n', str(ROOT / file)], check=True)

    def test_legacy_install_dry_run_is_inert(self):
        result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('disabled', result.stdout)

    def test_trial_rejects_unacknowledged_recovery(self):
        result = subprocess.run(['bash', str(ROOT / 'scripts/trial.sh'), '--passthrough'], capture_output=True)
        self.assertEqual(result.returncode, 2)

if __name__ == '__main__':
    unittest.main()
