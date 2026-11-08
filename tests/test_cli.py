"""Offline CLI checks: reject unsafe invocation before attempting device access."""
import pathlib
import subprocess
import tempfile
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

    def test_install_requires_explicit_profile_and_help_is_inert(self):
        result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        for script in ('install.sh', 'uninstall.sh'):
            result = subprocess.run(['bash', str(ROOT / script), '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('--dry-run', result.stdout)

    def test_persistent_mode_keeps_trials_bounded(self):
        for args in [('--persistent',), ('--observe', '--persistent'),
                     ('--passthrough', '--persistent'),
                     ('--filter', '--persistent', '--config', '/no-such-file', '--duration', '60'),
                     ('--filter', '--persistent', '--persistent', '--config', '/no-such-file')]:
            self.assertEqual(self.run_cli(*args).returncode, 2)
        with tempfile.NamedTemporaryFile(mode='w') as profile:
            profile.write('width_threshold=10\ntouch_threshold=20\nedge_width_threshold=5\nedge_percent=10\n')
            profile.flush()
            self.assertEqual(self.run_cli('--check-config', profile.name).returncode, 0)
            # /dev/null is deliberately the only opened descriptor in this check.
            self.assertEqual(self.run_cli('--filter', '--persistent', '--config', profile.name,
                                         '--session-uid', '1000', '--state-dir', '/tmp',
                                         '--device', '/dev/null').returncode, 1)
        self.assertEqual(self.run_cli('--check-config', str(ROOT / 'config/profile.example')).returncode, 2)

    def test_trial_rejects_unacknowledged_recovery(self):
        result = subprocess.run(['bash', str(ROOT / 'scripts/trial.sh'), '--passthrough'], capture_output=True)
        self.assertEqual(result.returncode, 2)

if __name__ == '__main__':
    unittest.main()
