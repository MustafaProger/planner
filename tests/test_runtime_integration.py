"""Runtime boundaries tested with isolated processes, no external API calls."""
import contextlib
import datetime as dt
import json
import os
import select
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from app import locks, monitoring, neftm, rosneft


PROVIDERS = [
    (neftm, 'neftm-sync', 'neftm-transactions.json'),
    (rosneft, 'rosneft-sync', 'rosneft-transactions.json'),
    (monitoring, 'monitoring-sync', 'monitoring-vehicles.json'),
]


def read_ready(process, timeout=5):
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    assert ready, 'Isolated child did not become ready in time'
    line = process.stdout.readline().strip()
    assert line, 'Isolated child exited before readiness'
    return line


@contextlib.contextmanager
def holding_lock(folder, name):
    code = (
        "from app.locks import file_lock; import sys; "
        "folder,name=sys.argv[1:]; "
        "\nwith file_lock(folder,name):"
        "\n print('ready',flush=True)"
        "\n sys.stdin.read(1)"
    )
    process = subprocess.Popen([sys.executable, '-c', code, str(folder), name],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        assert read_ready(process) == 'ready'
        yield process
    finally:
        if process.poll() is None:
            try:
                process.communicate(input='x', timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
        else:
            process.communicate(timeout=5)


def invoke(module, folder):
    return module.sync(folder) if module is monitoring else module.sync(folder, '2026-08-01', '2026-08-02')


@pytest.mark.parametrize('module,lock_name,snapshot_name', PROVIDERS)
@pytest.mark.parametrize('termination', ['normal', 'crash'])
def test_manual_and_worker_sync_share_cross_process_lock_and_recover_after_owner_exit(
        tmp_path, monkeypatch, module, lock_name, snapshot_name, termination):
    # Synthetic fixture credentials only; the network is forbidden below.
    (tmp_path/'neftm-api.key').write_text('synthetic-key')
    (tmp_path/'rosneft-credentials.json').write_text(json.dumps(
        {'login':'synthetic-login','password':'synthetic-password','contract':'synthetic-contract'}))
    snapshot = tmp_path/snapshot_name
    snapshot.write_text('{"retained":"existing provider snapshot"}')
    before = snapshot.read_bytes()
    entered = []

    class ProviderBodyEntered(Exception):
        pass

    def network_forbidden():
        entered.append(True)
        raise ProviderBodyEntered('Synthetic provider body, no request sent')

    monkeypatch.setattr(module.requests, 'Session', network_forbidden)
    with holding_lock(tmp_path, lock_name) as owner:
        with pytest.raises(ValueError, match='Источник уже обновляется'):
            invoke(module, tmp_path)
        assert entered == [] and snapshot.read_bytes() == before
        assert (tmp_path/(lock_name+'.lock')).stat().st_mode & 0o777 == 0o600
        if termination == 'crash':
            owner.kill()
            owner.wait(timeout=5)

    # Kernel releases locks even after process death. Body exceptions also release
    # both provider mutex and file lock, so another retry can enter immediately.
    for _ in range(2):
        with pytest.raises(ProviderBodyEntered):
            invoke(module, tmp_path)
    assert len(entered) == 2
    assert snapshot.read_bytes() == before
    with locks.file_lock(tmp_path, lock_name):
        pass


@pytest.mark.parametrize('module,lock_name,snapshot_name', PROVIDERS)
def test_another_provider_lock_does_not_block_this_provider(
        tmp_path, monkeypatch, module, lock_name, snapshot_name):
    (tmp_path/'neftm-api.key').write_text('synthetic-key')
    (tmp_path/'rosneft-credentials.json').write_text(json.dumps(
        {'login':'synthetic-login','password':'synthetic-password','contract':'synthetic-contract'}))
    different = 'monitoring-sync' if lock_name != 'monitoring-sync' else 'neftm-sync'

    class BodyReached(Exception):
        pass

    def network_forbidden():
        raise BodyReached()

    monkeypatch.setattr(module.requests, 'Session', network_forbidden)
    with holding_lock(tmp_path, different):
        with pytest.raises(BodyReached):
            invoke(module, tmp_path)


@contextlib.contextmanager
def isolated_http(folder, scheduler_mode):
    # The app import lives only in this child. Test collection and the parent's
    # environment/server singleton cannot accidentally target the working data.
    code = (
        "import logging; logging.getLogger('werkzeug').setLevel(logging.ERROR); "
        "from werkzeug.serving import make_server; from app.server import app; "
        "server=make_server('127.0.0.1',0,app); "
        "print(server.server_port,flush=True); server.serve_forever()"
    )
    environment = dict(os.environ, FLEET_DATA=str(folder), FLEET_SCHEDULER=scheduler_mode)
    process = subprocess.Popen([sys.executable, '-c', code], env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        port = int(read_ready(process, timeout=10))
        yield f'http://127.0.0.1:{port}/healthz'
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def response(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as value:
            return value.status, json.loads(value.read())
    except urllib.error.HTTPError as value:
        return value.code, json.loads(value.read())


def heartbeat(folder, *, age=0, status='running', expired=False):
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        'at':(now-dt.timedelta(seconds=age)).isoformat(),
        'pid':12345, 'status':status, 'private_note':'must-never-be-exposed',
        'jobs':{'test':{'deadline_at':(now+dt.timedelta(seconds=-10 if expired else 600)).isoformat()}}
    }
    temporary = folder/'heartbeat.tmp'
    temporary.write_text(json.dumps(payload))
    temporary.replace(folder/'refresh-heartbeat.json')


@pytest.mark.parametrize('scheduler_mode', ['external', 'embedded'])
def test_actual_health_http_distinguishes_web_from_worker_liveness(tmp_path, scheduler_mode):
    original_data = os.environ.get('FLEET_DATA')
    with isolated_http(tmp_path, scheduler_mode) as url:
        code, body = response(url)
        assert code == 503 and body == {'status':'degraded','web':'ok','updates':'unavailable'}

        heartbeat(tmp_path)
        code, body = response(url)
        assert code == 200 and body == {'status':'ok','web':'ok','updates':'ok'}

        for options in ({'age':120}, {'status':'stopping'}, {'expired':True}):
            heartbeat(tmp_path, **options)
            code, body = response(url)
            assert code == 503
            assert body == {'status':'degraded','web':'ok','updates':'unavailable'}
            assert 'must-never-be-exposed' not in json.dumps(body)

        (tmp_path/'refresh-heartbeat.json').write_text('not-json-with-private-details')
        assert response(url) == (503, {'status':'degraded','web':'ok','updates':'unavailable'})
    assert os.environ.get('FLEET_DATA') == original_data
    assert not (tmp_path/'fleet.sqlite').exists()
    assert not (tmp_path/'refresh-auto.json').exists()


def test_actual_health_http_explicit_disabled_mode_does_not_require_worker(tmp_path):
    original_data = os.environ.get('FLEET_DATA')
    with isolated_http(tmp_path, 'disabled') as url:
        assert response(url) == (200, {'status':'ok','web':'ok','updates':'unavailable'})
    assert os.environ.get('FLEET_DATA') == original_data
    assert not (tmp_path/'fleet.sqlite').exists()
