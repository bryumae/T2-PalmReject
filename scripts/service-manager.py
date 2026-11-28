#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Root session/sleep supervisor; filtering runs in a separate restricted unit."""
import fcntl
import json
import os
import pathlib
import pwd
import re
import shutil
import signal
import socket
import stat
import subprocess
import time

LIBEXEC = pathlib.Path('/usr/local/libexec/palmreject')
RUNTIME = pathlib.Path('/run/palmreject')
OWNERSHIP = pathlib.Path('/run/palmreject-worker-owned')
WORKER = 'palmreject-input.service'
DESCRIPTION = 'PalmReject restricted persistent input worker'
HARDWARE_UNITS = ('kait2en-suspend.service', 't2-services-suspend.service', 'sleep.target')
RETRY_DELAYS = (5, 10, 20, 40, 60)
HEALTHY_RESET_SECONDS = 60


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, timeout=8, **kwargs)


def notify(message):
    print(message.replace('\n', '; '), flush=True)
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.connect('\0' + address[1:] if address.startswith('@') else address)
            connection.sendall(message.encode())


class Lifecycle:
    """Bounded delayed retries; manual stops and sleep retain their intent."""
    def __init__(self, backend):
        self.backend = backend
        self.attempted = set()
        self.failures = {}
        self.retry_at = {}
        self.healthy_since = None
        self.session = None
        self.phase = 'waiting'
        self.deadline = 0
        self.sleeping = False
        self.resume = None
        self.waking = False

    def status(self, phase, detail):
        if self.phase != phase:
            self.phase = phase
            self.backend.status(detail)

    def fail(self, error, now=None):
        self.backend.stop()
        self.healthy_since = None
        if self.session is None:
            self.status('failed', f'Failed: {error}; waiting for session recovery')
            return
        now = time.monotonic() if now is None else now
        self.attempted.add(self.session)
        count = self.failures.get(self.session, 0) + 1
        self.failures[self.session] = count
        if count <= len(RETRY_DELAYS):
            delay = RETRY_DELAYS[count - 1]
            self.retry_at[self.session] = now + delay
            # Report each newly scheduled attempt even if the previous phase
            # was also retrying (for example a readiness check raised).
            self.phase = 'retrying'
            self.backend.status(f'Retry {count}/{len(RETRY_DELAYS)} in {delay}s after failure: {error}')
        else:
            self.retry_at.pop(self.session, None)
            self.status('failed', f'Failed: {error}; retry limit reached, restart service or log in again')

    def sleep(self, preparing):
        if preparing:
            self.sleeping = True
            self.resume = self.session if self.phase == 'filtering' and self.backend.alive() else None
            self.healthy_since = None
            self.backend.stop()
            self.status('suspended', 'Suspended; physical input released')
        else:
            self.sleeping = False
            self.waking = True

    def tick(self, sessions, now):
        existing = {session for session, active in sessions}
        self.attempted.intersection_update(existing)
        self.failures = {key: value for key, value in self.failures.items() if key in existing}
        self.retry_at = {key: value for key, value in self.retry_at.items() if key in existing}
        if self.sleeping:
            return
        if self.waking:
            if not self.backend.hardware_ready():
                return
            if self.resume in existing:
                self.attempted.discard(self.resume)
            self.resume = None
            self.waking = False
            self.deadline = now + 60
            self.status('waiting', 'Resumed; waiting for session readiness or scheduled retry')
        active = [session for session, enabled in sessions if enabled]
        selected = active[0] if len(active) == 1 else None
        if selected != self.session:
            self.backend.stop()
            self.session = selected
            self.healthy_since = None
            self.deadline = now + 60
            self.status('waiting', 'Waiting for exactly one active Wayland session and KWin')
        if selected is None:
            return
        if self.phase in ('starting', 'filtering'):
            if not self.backend.alive():
                if self.backend.exit_is_failure():
                    self.fail('input worker or helper exited', now)
                else:
                    self.backend.stop()
                    self.healthy_since = None
                    self.status('stopped', 'Stopped for this login; restart service to retry')
            elif self.backend.ready():
                self.status('filtering', f'Filtering for session {selected}')
                if self.healthy_since is None:
                    self.healthy_since = now
                elif now - self.healthy_since >= HEALTHY_RESET_SECONDS:
                    self.failures.pop(selected, None)
            elif now >= self.deadline:
                self.fail('input/cancellation readiness timed out', now)
            return
        if selected in self.retry_at:
            if now < self.retry_at[selected]:
                return
            self.retry_at.pop(selected)
            self.attempted.discard(selected)
            self.deadline = now + 60
            self.status('waiting', 'Retrying; waiting for KWin readiness')
        if selected in self.attempted:
            if self.failures.get(selected, 0) > len(RETRY_DELAYS):
                self.status('failed', 'Failed: retry limit reached; restart service or log in again')
            else:
                self.status('stopped', 'Stopped for this login; restart service to retry')
            return
        if self.backend.session_ready():
            self.attempted.add(selected)
            try:
                self.backend.start()
            except Exception as error:
                self.fail(error, now)
                return
            self.deadline = now + 30
            self.status('starting', 'Starting restricted input worker; waiting for cancellation readiness')
        elif now >= self.deadline:
            self.fail('KWin/user bus not ready within 60 seconds', now)


class Backend:
    def __init__(self, uid):
        self.user = pwd.getpwuid(uid)
        if uid == 0:
            raise ValueError('A nonroot session UID is required')
        self.helper = None
        self.announced = False
        self.started = False
        self.physical = None
        self.environment = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                            'XDG_RUNTIME_DIR': f'/run/user/{uid}',
                            'DBUS_SESSION_BUS_ADDRESS': f'unix:path=/run/user/{uid}/bus'}

    def user_command(self, *args):
        return ['/usr/bin/runuser', '-u', self.user.pw_name, '--', '/usr/bin/python3',
                str(LIBEXEC / 'gesture-helper.py'), *args]

    def status(self, message):
        notify('STATUS=' + message)

    def properties(self, unit):
        result = run(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'LoadState',
                      '-p', 'Result', '-p', 'Description', '-p', 'ExecStart', '-p', 'Transient'], capture_output=True)
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)

    def recover(self):
        """Clean only our transient worker after an interrupted supervisor."""
        props = self.properties(WORKER)
        if props.get('LoadState') != 'not-found':
            if (props.get('Transient') != 'yes' or props.get('Description') != DESCRIPTION or
                    f'path={LIBEXEC}/palmreject ;' not in props.get('ExecStart', '')):
                raise RuntimeError(f'Unmanaged {WORKER}; refusing cleanup')
            self.started = True
        elif OWNERSHIP.exists():
            st = OWNERSHIP.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077 or OWNERSHIP.read_text() != DESCRIPTION:
                raise RuntimeError('Unsafe worker ownership marker')
            self.started = True
        elif pathlib.Path('/run/systemd/system.control/' + WORKER + '.d').exists():
            raise RuntimeError('Unowned worker property directory; inspect before startup')
        self.stop()

    def hardware_ready(self):
        for unit in HARDWARE_UNITS:
            props = self.properties(unit)
            if props.get('LoadState') == 'not-found':
                continue
            if props.get('ActiveState') != 'inactive' or props.get('Result', 'success') != 'success':
                return False
        return True

    def session_ready(self):
        if not pathlib.Path(self.environment['XDG_RUNTIME_DIR'], 'bus').is_socket():
            return False
        try:
            subprocess.run(self.user_command('--check-session'), env=self.environment,
                           timeout=2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (subprocess.SubprocessError, OSError):
            return False

    def start(self):
        if self.properties('palmreject-trial.service').get('ActiveState') in ('active', 'activating'):
            raise RuntimeError('A trial is already running')
        if self.properties(WORKER).get('LoadState') != 'not-found':
            raise RuntimeError(f'Existing {WORKER}; inspect it before restarting')
        state = RUNTIME / 'state'
        state.mkdir(mode=0o700)
        os.chown(state, 0, self.user.pw_gid)
        # RestrictSUIDSGID blocks setting the directory's setgid bit. Give the
        # root worker this primary group instead, so its socket has that group.
        state.chmod(0o750)
        probe = run([str(LIBEXEC / 'palmreject'), '--probe'], capture_output=True).stdout
        match = re.match(r'device=(/dev/input/event[0-9]+) ', probe)
        if not match:
            raise RuntimeError('Invalid physical probe result')
        physical = match[1]
        self.physical = physical
        properties = [
            'BindsTo=palmreject.service', 'After=palmreject.service', 'Conflicts=sleep.target',
            'Before=sleep.target kait2en-suspend.service t2-services-suspend.service',
            'Restart=no', 'TimeoutStopSec=2', 'KillMode=control-group',
            f'Group={self.user.pw_gid}',
            'NoNewPrivileges=yes', 'ProtectSystem=strict', 'ProtectHome=yes',
            'PrivateNetwork=yes', 'RestrictAddressFamilies=AF_UNIX AF_NETLINK',
            'CapabilityBoundingSet=', 'ProtectKernelTunables=yes', 'ProtectKernelModules=yes',
            'ProtectControlGroups=yes', 'RestrictSUIDSGID=yes', 'LockPersonality=yes',
            'DevicePolicy=closed', 'DeviceAllow=/dev/uinput rw', f'DeviceAllow={physical} r',
            f'ReadWritePaths={state}']
        args = ['systemd-run', '--unit=' + WORKER, '--description=' + DESCRIPTION, '--service-type=exec']
        for prop in properties:
            args += ['-p', prop]
        args += [str(LIBEXEC / 'palmreject'), '--filter', '--persistent', '--device', physical,
                 '--config', '/etc/palmreject/profile.conf', '--session-uid', str(self.user.pw_uid),
                 '--state-dir', str(state)]
        fd = os.open(OWNERSHIP, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as marker:
            marker.write(DESCRIPTION)
        self.started = True
        run(args)

    def alive(self):
        return self.started and self.properties(WORKER).get('ActiveState') == 'active' and (
            self.helper is None or self.helper.poll() is None)

    def exit_is_failure(self):
        props = self.properties(WORKER)
        # A deliberately stopped worker exits successfully. A helper exiting
        # while its worker still runs is an unexpected loss of cancellation.
        return (props.get('ActiveState') == 'active' or
                props.get('Result', 'success') != 'success')

    def ready(self):
        state = RUNTIME / 'state'
        announcement = state / 'virtual-device'
        if not self.announced and announcement.is_file() and announcement.stat().st_size:
            virtual = announcement.read_text()
            if not re.fullmatch(r'/dev/input/event[0-9]+', virtual):
                raise RuntimeError('Invalid virtual node announcement')
            device = (pathlib.Path('/sys/class/input') / pathlib.Path(virtual).name / 'device').resolve(strict=True)
            if not str(device).startswith('/sys/devices/virtual/input/') or (
                    device / 'name').read_text().strip() != 'PalmReject MacBookPro16,1 Touchpad':
                raise RuntimeError('Unexpected virtual device identity')
            run(['systemctl', 'set-property', '--runtime', WORKER, 'DeviceAllow=/dev/uinput rw',
                 f'DeviceAllow={self.physical} r', f'DeviceAllow={virtual} rw'])
            self.helper = subprocess.Popen(self.user_command('--socket', str(state / 'control.sock')),
                                           env=self.environment)
            self.announced = True
        return self.announced and (state / 'ready').is_file()

    def stop(self):
        if self.started and self.properties(WORKER).get('LoadState') != 'not-found':
            run(['systemctl', 'stop', WORKER])
        if self.helper is not None:
            if self.helper.poll() is None:
                self.helper.terminate()
                try:
                    self.helper.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.helper.kill()
                    self.helper.wait(timeout=2)
            self.helper = None
        if self.started:
            run(['systemctl', 'revert', WORKER])
            subprocess.run(['systemctl', 'reset-failed', WORKER], check=False,
                           timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.started = self.announced = False
        OWNERSHIP.unlink(missing_ok=True)
        state = RUNTIME / 'state'
        if state.exists():
            shutil.rmtree(state)


def main():
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib
    if os.geteuid() != 0:
        raise RuntimeError('Run through the installed system service')
    settings = json.loads(pathlib.Path('/etc/palmreject/settings.json').read_text())
    uid = settings['session_uid']
    if type(uid) is not int or uid <= 0:
        raise ValueError('Invalid configured UID')
    lock = os.open('/run/palmreject-input.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(lock, 'w') as locked:
        st = os.fstat(locked.fileno())
        if st.st_uid != 0 or not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022:
            raise RuntimeError('Unsafe lifecycle lock')
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        RUNTIME.mkdir(mode=0o750, exist_ok=True)
        os.chown(RUNTIME, 0, pwd.getpwuid(uid).pw_gid)
        RUNTIME.chmod(0o750)
        backend = Backend(uid)
        backend.recover()
        lifecycle = Lifecycle(backend)
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        manager = dbus.Interface(bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1'),
                                 'org.freedesktop.login1.Manager')
        inhibitor = None
        loop = GLib.MainLoop()

        def acquire():
            return manager.Inhibit('sleep', 'PalmReject', 'Release trackpad before sleep', 'delay').take()

        def sleep(preparing):
            nonlocal inhibitor
            try:
                lifecycle.sleep(bool(preparing))
                if not preparing and inhibitor is None:
                    inhibitor = acquire()
            except Exception as error:
                backend.status(f'Sleep handling failed: {error}')
                loop.quit()
            finally:
                if preparing and inhibitor is not None:
                    os.close(inhibitor)
                    inhibitor = None

        def tick():
            try:
                sessions = []
                for session, user, name, seat, path in manager.ListSessions(timeout=2):
                    if int(user) != uid:
                        continue
                    props = bus.get_object('org.freedesktop.login1', path).GetAll(
                        'org.freedesktop.login1.Session', dbus_interface='org.freedesktop.DBus.Properties', timeout=2)
                    if props['Type'] == 'wayland' and props['Class'] == 'user':
                        sessions.append((str(session), bool(props['Active'])))
                lifecycle.tick(sessions, time.monotonic())
            except Exception as error:
                try:
                    lifecycle.fail(error)
                except Exception as cleanup_error:
                    backend.status(f'Cleanup failed: {cleanup_error}')
                    loop.quit()
            return True

        bus.add_signal_receiver(sleep, signal_name='PrepareForSleep',
                                dbus_interface='org.freedesktop.login1.Manager',
                                bus_name='org.freedesktop.login1')
        inhibitor = acquire()
        preparing = bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1').Get(
            'org.freedesktop.login1.Manager', 'PreparingForSleep',
            dbus_interface='org.freedesktop.DBus.Properties')
        if preparing:
            sleep(True)
        for sig in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda: (loop.quit(), False)[1])
        notify('READY=1\nSTATUS=Waiting for configured Wayland session')
        GLib.timeout_add(1000, tick)
        try:
            loop.run()
        finally:
            backend.stop()
            if inhibitor is not None:
                os.close(inhibitor)


if __name__ == '__main__':
    main()
