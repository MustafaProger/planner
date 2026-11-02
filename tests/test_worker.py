import datetime as dt
import json
import socket
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import health, worker
from deploy import preflight, backup


class Stop:
    def __init__(self, clock, after=99):
        self.clock = clock
        self.after = after
        self.waits = 0

    def is_set(self):
        return self.waits >= self.after

    def wait(self, seconds):
        self.clock[0] += seconds
        self.waits += 1
        return self.is_set()


class Service:
    def __init__(self, values):
        self.values = iter(values)
        self.started = False
        self.stopped = None

    def start_scheduler(self):
        self.started = True

    def runtime_health(self):
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value

    def stop(self, join_timeout):
        self.stopped = join_timeout


def test_worker_exits_on_dead_scheduler_and_requests_bounded_shutdown():
    service = Service([{'healthy': True}, {'healthy': False, 'reason': 'stalled'}])
    clock = [0]
    messages = []
    assert worker.supervise(service, Stop(clock), monotonic=lambda: clock[0], notifier=messages.append) == 1
    assert service.started and service.stopped == 30
    assert messages[0].startswith('READY=1')
    assert 'WATCHDOG=1' in messages and messages[-1] == 'STOPPING=1'


def test_provider_outage_is_not_a_process_failure():
    service = Service([{'healthy': True, 'provider_status': 'error'}]*2)
    clock = [0]
    messages = []
    assert worker.supervise(service, Stop(clock, after=2), monotonic=lambda: clock[0], notifier=messages.append) == 0
    assert service.stopped == 30
    assert messages.count('WATCHDOG=1') == 2


def test_worker_startup_grace_is_bounded_and_no_false_ready():
    service = Service([{'healthy': False}]*10)
    clock = [0]
    messages = []
    result = worker.supervise(service, Stop(clock), startup_grace=10,
                              monotonic=lambda: clock[0], notifier=messages.append)
    assert result == 1 and clock[0] == 10
    assert not any(m.startswith('READY=') for m in messages)


def test_runtime_exception_causes_restart_without_echoing_secrets(caplog):
    service = Service([{'healthy': True}, ValueError('credential-value-must-not-appear')])
    clock = [0]
    messages = []
    assert worker.supervise(service, Stop(clock), monotonic=lambda: clock[0], notifier=messages.append) == 1
    assert 'credential-value' not in caplog.text
    assert 'credential-value' not in '\n'.join(messages)


def test_startup_exception_still_stops_service(caplog):
    class Bad(Service):
        def start_scheduler(self):
            raise ValueError('secret-placeholder')
    service = Bad([])
    assert worker.supervise(service, notifier=lambda _: None) == 1
    assert service.stopped == 30 and 'secret-placeholder' not in caplog.text


def test_sd_notify_uses_local_socket_and_does_not_require_systemd():
    assert worker.notify('WATCHDOG=1', {}) is False
    with tempfile.TemporaryDirectory(dir='/tmp') as folder:
        path = str(Path(folder)/'notify')
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind(path)
            receiver.settimeout(1)
            assert worker.notify('READY=1\nWATCHDOG=1', {'NOTIFY_SOCKET': path})
            assert receiver.recv(128) == b'READY=1\nWATCHDOG=1'
        assert worker.notify('WATCHDOG=1', {'NOTIFY_SOCKET': path}) is False


@pytest.mark.parametrize('change,healthy', [
    ({}, True),
    ({'status': 'stopping'}, False),
    ({'at': '2026-10-30T08:00:00+00:00'}, False),
    ({'at': '2026-10-30T10:00:00+00:00'}, False),
    ({'at': '2026-10-30T09:00:00'}, False),
    ({'jobs': {'task': {'deadline_at': '2026-10-30T08:59:00+00:00'}}}, False),
    ({'jobs': {'task': {'deadline_at': '2026-10-30T09:10:00+00:00'}}}, True),
    ({'jobs': {'task': {}}}, False),
])
def test_persisted_liveness_is_honest(tmp_path, change, healthy):
    now = dt.datetime(2026, 10, 30, 9, 0, 10, tzinfo=dt.timezone.utc)
    state = {'at': '2026-10-30T09:00:00+00:00', 'pid': 123, 'status': 'running', 'jobs': {}}
    state.update(change)
    (tmp_path/'refresh-heartbeat.json').write_text(json.dumps(state))
    assert health.read_worker_health(tmp_path, now=now)['healthy'] is healthy


def test_missing_or_malformed_heartbeat_does_not_report_healthy(tmp_path):
    assert health.read_worker_health(tmp_path)['healthy'] is False
    (tmp_path/'refresh-heartbeat.json').write_text('{broken')
    assert health.read_worker_health(tmp_path)['healthy'] is False


@pytest.fixture
def provisioned(tmp_path):
    data = tmp_path/'data'
    data.mkdir(mode=0o700)
    with sqlite3.connect(data/'fleet.sqlite') as connection:
        connection.executescript("""create table workspace_meta(key text,body text);
            insert into workspace_meta values('initialized','1');
            create table users(id integer);insert into users values(1);
            create table snapshot(id integer);insert into snapshot values(1);""")
    (data/'session.key').write_text('test-session-key')
    for name in preflight.PROVIDERS.values():
        (data/name).write_text('test-placeholder')
    for path in data.iterdir():
        path.chmod(0o600)
    return data


def test_preflight_validates_existing_data_without_mutation(provisioned):
    before = {p.name: p.read_bytes() for p in provisioned.iterdir()}
    assert preflight.check(provisioned, platform='linux') == []
    assert before == {p.name: p.read_bytes() for p in provisioned.iterdir()}


def test_preflight_rejects_mac_route_on_linux_without_changing_it(provisioned):
    path = provisioned/'transtrade-network.json'
    path.write_text('{"interface":"en0"}')
    errors = preflight.check(provisioned, platform='linux')
    assert any('macOS' in item for item in errors)
    assert path.read_text() == '{"interface":"en0"}'
    assert preflight.check(provisioned, platform='darwin') == []


def test_preflight_fails_missing_secret_and_insecure_permissions(provisioned):
    (provisioned/'session.key').unlink()
    (provisioned/'transtrade-credentials.json').chmod(0o644)
    errors = preflight.check(provisioned, platform='linux')
    assert any('session.key' in item for item in errors)
    assert any('0600' in item for item in errors)


def test_preflight_does_not_initialize_an_empty_database(tmp_path):
    tmp_path.chmod(0o700)
    before = list(tmp_path.iterdir())
    assert preflight.check(tmp_path)
    assert list(tmp_path.iterdir()) == before


def test_systemd_units_have_separate_processes_and_persistent_data():
    root = Path(__file__).resolve().parents[1]
    web = (root/'deploy/fleet-web.service').read_text()
    background = (root/'deploy/fleet-worker.service').read_text()
    for text in (web, background):
        assert 'FLEET_SCHEDULER=external' in text
        assert 'Restart=always' in text and 'WantedBy=multi-user.target' in text
        assert 'UMask=0077' in text and 'StateDirectoryMode=0700' in text
        assert 'ExecStartPre=' in text and 'deploy/preflight.py' in text
    assert '-m app.server' in web and 'WatchdogSec=' not in web
    assert '-m app.worker' in background and 'WatchdogSec=45' in background
    assert 'Type=notify' in background and 'NotifyAccess=main' in background


def test_database_backup_is_consistent_private_and_never_overwrites(provisioned, tmp_path):
    folder = tmp_path/'backups'
    folder.mkdir(mode=0o700)
    destination = folder/'before-release.sqlite'
    secrets_before = (provisioned/'session.key').read_bytes()
    backup.backup(provisioned, destination)
    with sqlite3.connect(destination) as connection:
        assert connection.execute('pragma integrity_check').fetchone()[0] == 'ok'
        assert connection.execute('select id from users').fetchall() == [(1,)]
    assert destination.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in folder.iterdir()] == ['before-release.sqlite']
    assert (provisioned/'session.key').read_bytes() == secrets_before
    content = destination.read_bytes()
    with pytest.raises(FileExistsError):
        backup.backup(provisioned, destination)
    assert destination.read_bytes() == content
