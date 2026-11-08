"""Lifecycle and worker command tests; no real bus, services or devices."""
import importlib.util
import pathlib
import subprocess
import unittest
from unittest.mock import patch, Mock

SPEC = importlib.util.spec_from_file_location('service_manager', pathlib.Path(__file__).resolve().parents[1] / 'scripts/service-manager.py')
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


class Backend:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.running = False
        self.is_ready = True
        self.kwin = True
        self.hardware = True
        self.messages = []
    def start(self):
        self.started += 1
        self.running = True
    def stop(self):
        self.stopped += 1
        self.running = False
    def alive(self):
        return self.running
    def ready(self):
        return self.is_ready
    def session_ready(self):
        return self.kwin
    def hardware_ready(self):
        return self.hardware
    def status(self, text):
        self.messages.append(text)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.life = service.Lifecycle(self.backend)
    def start(self):
        self.life.tick([('s1', True)], 1)
        self.life.tick([('s1', True)], 2)
        self.assertEqual(self.life.phase, 'filtering')
    def test_waits_for_unique_session_and_kwin(self):
        self.life.tick([], 1)
        self.life.tick([('s1', True), ('s2', True)], 2)
        self.assertEqual(self.backend.started, 0)
        self.backend.kwin = False
        self.life.tick([('s1', True)], 3)
        self.life.tick([('s1', True)], 62)
        self.assertEqual(self.backend.started, 0)
        self.life.tick([('s1', True)], 63)
        self.backend.kwin = True
        self.life.tick([('s1', True)], 64)
        self.assertEqual(self.backend.started, 0)
        self.life.tick([('s2', True)], 65)
        self.assertEqual(self.backend.started, 1)
    def test_failure_latches_until_new_login(self):
        self.start()
        self.backend.running = False
        self.life.tick([('s1', True)], 3)
        self.assertEqual(self.life.phase, 'failed')
        self.life.tick([('s1', False)], 4)
        self.life.tick([('s1', True)], 5)
        self.assertEqual(self.backend.started, 1)
        self.life.tick([('s2', True)], 6)
        self.assertEqual(self.backend.started, 2)
    def test_logout_releases_input(self):
        self.start()
        self.life.tick([], 3)
        self.assertFalse(self.backend.running)
    def test_missing_cancellation_or_helper_timeout_stops_once(self):
        self.backend.is_ready = False
        self.life.tick([('s1', True)], 1)
        self.life.tick([('s1', True)], 31)
        self.assertFalse(self.backend.running)
        self.life.tick([('s1', True)], 32)
        self.assertEqual(self.backend.started, 1)
    def test_sleep_waits_for_hardware_and_resumes_healthy_worker(self):
        self.start()
        self.life.sleep(True)
        self.assertFalse(self.backend.running)
        self.life.tick([('s1', True)], 10)
        self.assertEqual(self.backend.started, 1)
        self.life.sleep(False)
        self.backend.hardware = False
        self.life.tick([('s1', True)], 11)
        self.assertEqual(self.backend.started, 1)
        self.backend.hardware = True
        self.life.tick([('s1', True)], 12)
        self.assertEqual(self.backend.started, 2)
    def test_manual_worker_stop_and_failure_survive_sleep(self):
        self.start()
        self.backend.running = False
        # Even if the monitor has not seen the exit yet, sleep must not revive it.
        self.life.sleep(True)
        self.life.sleep(False)
        self.life.tick([('s1', True)], 20)
        self.assertEqual(self.backend.started, 1)
    def test_restart_supervisor_permits_retry(self):
        self.start()
        self.life.fail('helper failure')
        self.life.tick([('s1', True)], 3)
        self.assertEqual(self.backend.started, 1)
        self.life = service.Lifecycle(self.backend)
        self.life.tick([('s1', True)], 4)
        self.assertEqual(self.backend.started, 2)
    def test_worker_hardening_and_lifetime_binding(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp, patch.object(service, 'RUNTIME', pathlib.Path(temp)), patch.object(service, 'OWNERSHIP', pathlib.Path(temp) / 'owned'), patch.object(service.os, 'chown'), patch.object(service, 'run') as run:
            backend = service.Backend(1000)
            backend.properties = lambda unit: {'LoadState': 'not-found', 'ActiveState': 'inactive'}
            run.return_value = subprocess.CompletedProcess([], 0, 'device=/dev/input/event42 vendor=05ac\n')
            backend.start()
            args = run.call_args.args[0]
            for prop in ('BindsTo=palmreject.service', 'Restart=no', 'DevicePolicy=closed',
                         'CapabilityBoundingSet=', 'ProtectHome=yes', 'DeviceAllow=/dev/input/event42 r',
                         'RestrictSUIDSGID=yes', f'Group={backend.user.pw_gid}'):
                self.assertIn(prop, args)
            self.assertEqual((pathlib.Path(temp) / 'state').stat().st_mode & 0o7777, 0o750)
            self.assertIn('--persistent', args)
            self.assertNotIn('--duration', args)
            self.assertNotIn('DeviceAllow=char-input', args)
    def test_failed_t2_resume_does_not_pass_hardware_gate(self):
        backend = service.Backend(1000)
        backend.properties = Mock(return_value={'LoadState': 'loaded', 'ActiveState': 'failed', 'Result': 'exit-code'})
        self.assertFalse(backend.hardware_ready())
    def test_crash_recovery_refuses_unmanaged_worker(self):
        backend = service.Backend(1000)
        backend.properties = lambda unit: {'LoadState': 'loaded', 'Transient': 'no', 'ExecStart': 'other'}
        with self.assertRaises(RuntimeError):
            backend.recover()
    def test_crash_recovery_recognizes_own_transient_worker(self):
        backend = service.Backend(1000)
        backend.properties = lambda unit: {'LoadState': 'loaded', 'Transient': 'yes',
                                          'Description': service.DESCRIPTION,
                                          'ExecStart': f'{{ path={service.LIBEXEC}/palmreject ; argv[]=... }}'}
        backend.stop = Mock()
        backend.recover()
        self.assertTrue(backend.started)
        backend.stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
