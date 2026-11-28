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
        self.failed = True
        self.messages = []
    def start(self):
        self.started += 1
        self.running = True
    def stop(self):
        self.stopped += 1
        self.running = False
    def alive(self):
        return self.running
    def exit_is_failure(self):
        return self.failed
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
    def test_failure_retries_only_after_delay_and_while_session_active(self):
        self.start()
        self.backend.running = False
        self.life.tick([('s1', True)], 3)
        self.assertEqual(self.life.phase, 'retrying')
        self.life.tick([('s1', False)], 4)
        self.life.tick([('s1', True)], 5)
        self.assertEqual(self.backend.started, 1)
        self.life.tick([('s1', False)], 8)
        self.assertEqual(self.backend.started, 1)
        self.life.tick([('s1', True)], 9)
        self.assertEqual(self.backend.started, 2)
    def test_logout_releases_input(self):
        self.start()
        self.life.tick([], 3)
        self.assertFalse(self.backend.running)
    def test_missing_cancellation_or_helper_timeout_retries_with_new_deadline(self):
        self.backend.is_ready = False
        self.life.tick([('s1', True)], 1)
        self.life.tick([('s1', True)], 31)
        self.assertFalse(self.backend.running)
        self.life.tick([('s1', True)], 32)
        self.assertEqual(self.backend.started, 1)
        self.life.tick([('s1', True)], 36)
        self.assertEqual(self.backend.started, 2)
        self.assertEqual(self.life.deadline, 66)
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
    def test_successful_worker_stop_is_not_retried(self):
        self.start()
        self.backend.running = False
        self.backend.failed = False
        self.life.tick([('s1', True)], 3)
        self.assertEqual(self.life.phase, 'stopped')
        self.life.tick([('s1', True)], 1000)
        self.assertEqual(self.backend.started, 1)
    def test_retry_limit_and_exponential_delays(self):
        self.start()
        now = 3
        for retry, delay in enumerate(service.RETRY_DELAYS, 1):
            self.backend.running = False
            self.life.tick([('s1', True)], now)
            self.assertEqual(self.life.retry_at['s1'], now + delay)
            self.life.tick([('s1', True)], now + delay - 0.1)
            self.assertEqual(self.backend.started, retry)
            now += delay
            self.life.tick([('s1', True)], now)
            self.assertEqual(self.backend.started, retry + 1)
            self.life.tick([('s1', True)], now + 1)
            now += 2
        self.backend.running = False
        self.life.tick([('s1', True)], now)
        self.assertEqual(self.life.phase, 'failed')
        self.assertNotIn('s1', self.life.retry_at)
        self.life.tick([('s1', True)], now + 10000)
        self.assertEqual(self.backend.started, 6)
        self.life.tick([('s2', True)], now + 10001)
        self.assertEqual(self.backend.started, 7)
    def test_healthy_operation_resets_retry_budget(self):
        self.start()
        self.backend.running = False
        self.life.tick([('s1', True)], 3)
        self.life.tick([('s1', True)], 8)
        self.life.tick([('s1', True)], 9)
        self.assertEqual(self.life.failures['s1'], 1)
        self.life.tick([('s1', True)], 68)
        self.assertEqual(self.life.failures['s1'], 1)
        self.life.tick([('s1', True)], 69)
        self.assertNotIn('s1', self.life.failures)
        self.backend.running = False
        self.life.tick([('s1', True)], 70)
        self.assertEqual(self.life.retry_at['s1'], 75)
    def test_pending_retry_waits_for_sleep_and_hardware(self):
        self.start()
        self.backend.running = False
        self.life.tick([('s1', True)], 3)
        self.life.sleep(True)
        self.life.tick([('s1', True)], 20)
        self.assertEqual(self.backend.started, 1)
        self.life.sleep(False)
        self.backend.hardware = False
        self.life.tick([('s1', True)], 21)
        self.assertEqual(self.backend.started, 1)
        self.backend.hardware = True
        self.life.tick([('s1', True)], 22)
        self.assertEqual(self.backend.started, 2)
    def test_start_exception_schedules_retry_after_cleanup(self):
        self.backend.start = Mock(side_effect=RuntimeError('busy trackpad'))
        self.life.tick([('s1', True)], 1)
        self.assertEqual(self.life.phase, 'retrying')
        self.assertFalse(self.backend.running)
        self.assertEqual(self.life.retry_at['s1'], 6)
    def test_readiness_timeout_retries(self):
        self.backend.kwin = False
        self.life.tick([('s1', True)], 1)
        self.life.tick([('s1', True)], 61)
        self.assertEqual(self.life.phase, 'retrying')
        self.backend.kwin = True
        self.life.tick([('s1', True)], 65)
        self.assertEqual(self.backend.started, 0)
        self.life.tick([('s1', True)], 66)
        self.assertEqual(self.backend.started, 1)
    def test_exhausted_budget_survives_suspend(self):
        self.start()
        for now in range(len(service.RETRY_DELAYS) + 1):
            self.life.fail('persistent failure', now)
        self.life.sleep(True)
        self.life.sleep(False)
        self.life.tick([('s1', True)], 1000)
        self.assertEqual(self.life.phase, 'failed')
        self.assertEqual(self.backend.started, 1)
    def test_backend_distinguishes_failure_from_successful_stop(self):
        backend = service.Backend(1000)
        for props, expected in [
                ({'ActiveState': 'failed', 'Result': 'exit-code'}, True),
                ({'ActiveState': 'active', 'Result': 'success'}, True),
                ({'ActiveState': 'inactive', 'Result': 'success'}, False),
                ({'LoadState': 'not-found', 'ActiveState': 'inactive'}, False)]:
            backend.properties = Mock(return_value=props)
            self.assertEqual(backend.exit_is_failure(), expected)
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
