import datetime as dt
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from flask import Flask, jsonify, request, session
from functools import wraps
from app import refresh, neftm, rosneft, transtrade, monitoring, monitoring_history


def wait(service, seconds=3):
    until = time.monotonic()+seconds
    while service.running and time.monotonic() < until:
        time.sleep(.01)
    assert not service.running
    return service.status()


@pytest.fixture
def service(tmp_path, monkeypatch):
    db = tmp_path/'fleet.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('create table audit(at text,user_id integer,action text,detail text)')
        c.execute('create table protected(value text)')
        c.execute("insert into protected values('manual changes remain')")
    for module in (rosneft, transtrade, monitoring):
        monkeypatch.setattr(module, 'configured', lambda _: False)
    return refresh.RefreshService(tmp_path, db, lambda: {'vehicles': ['А123АА777']})


def test_period_moscow_and_provider_limit(monkeypatch):
    monkeypatch.setattr(refresh, 'now', lambda: dt.datetime(2026, 11, 1, 0, 10, tzinfo=refresh.MSK))
    assert refresh.period() == ('2026-11-01', '2026-11-01')
    assert refresh.period('2026-08-01', '2026-08-31') == ('2026-08-01', '2026-08-31')
    for dates in [(None, '2026-08-01'), ('2026-08-01', None), ('2026-08-01', '2026-09-01'), ('2026-08-02', '2026-08-01'), ('bad', 'bad')]:
        with pytest.raises(ValueError):
            refresh.period(*dates)


def test_unconfigured_sources_do_not_run_or_change_data(service, monkeypatch):
    for module in (rosneft, transtrade, monitoring, neftm):
        monkeypatch.setattr(module, 'sync', lambda *_: pytest.fail('Unconfigured API called'))
    service.start('2026-08-01', '2026-08-31', user_id=1)
    state = wait(service)
    assert state['status'] == 'idle'
    assert set(s['status'] for s in state['sources'].values()) == {'unconfigured'}
    with sqlite3.connect(service.db_path) as c:
        assert c.execute('select value from protected').fetchone()[0] == 'manual changes remain'
        assert c.execute('select user_id,action from audit').fetchone() == (1, 'refresh manual')


def test_failure_isolated_and_previous_success_retained(service, monkeypatch):
    monkeypatch.setattr(transtrade, 'configured', lambda _: True)
    monkeypatch.setattr(rosneft, 'configured', lambda _: True)
    calls = []
    monkeypatch.setattr(transtrade, 'sync', lambda *args: calls.append(('tt', args[2:])) or {'received': 5})
    monkeypatch.setattr(rosneft, 'sync', lambda *args: calls.append(('rn', args[1:])) or {'rows': [1]})
    service.start('2026-08-01', '2026-08-31')
    first = wait(service)
    assert first['status'] == 'success'
    def fail(*args):
        raise ValueError('Источник временно недоступен.')
    monkeypatch.setattr(transtrade, 'sync', fail)
    service.start('2026-08-01', '2026-08-31')
    second = wait(service)
    assert second['status'] == 'partial'
    assert second['sources']['rosneft']['status'] == 'success'
    assert second['sources']['transtrade']['message'] == 'Источник временно недоступен.'
    assert second['sources']['transtrade']['last_success_at'] == first['sources']['transtrade']['last_success_at']
    assert second['last_success_at'] == first['last_success_at']
    assert calls == [('tt', ('2026-08-01', '2026-08-31')), ('rn', ('2026-08-01', '2026-08-31')), ('rn', ('2026-08-01', '2026-08-31'))]


def test_overlap_same_and_other_service_does_not_duplicate(service, monkeypatch):
    monkeypatch.setattr(transtrade, 'configured', lambda _: True)
    gate, entered = threading.Event(), threading.Event()
    calls = []
    def sync(*args):
        calls.append(args)
        entered.set()
        gate.wait(2)
        return {'received': 1}
    monkeypatch.setattr(transtrade, 'sync', sync)
    one = service.start()
    assert entered.wait(1)
    try:
        assert service.start()['accepted'] is False
        other = refresh.RefreshService(service.data_dir, service.db_path, lambda: {})
        duplicate = other.start()
        assert not duplicate['accepted'] and duplicate['id'] == one['id']
        assert other.status()['status'] == 'running'
    finally:
        gate.set()
        wait(service)
    assert len(calls) == 1


def test_interrupted_status_is_honest(service):
    service._save({'status': 'running', 'sources': {}})
    assert service.status()['status'] == 'interrupted'


def test_monitoring_auto_only_yesterday_and_manual_completed_days(service, monkeypatch):
    monkeypatch.setattr(refresh, 'now', lambda: dt.datetime(2026, 10, 29, 12, tzinfo=refresh.MSK))
    monkeypatch.setattr(monitoring, 'configured', lambda _: True)
    monkeypatch.setattr(monitoring, 'sync', lambda _: {'rows': [1, 2]})
    current = {'value': None}
    calls = []
    def start(_, names, a, b, refresh=False):
        calls.append((names, a, b, refresh))
        current['value'] = {'id': 'test-job', 'status': 'complete'}
        return current['value']
    monkeypatch.setattr(monitoring_history, 'start', start)
    monkeypatch.setattr(monitoring_history, 'job_status', lambda _: current['value'])
    service.start(trigger='automatic')
    assert wait(service)['status'] == 'success'
    service.start('2026-10-27', '2026-10-31')
    assert wait(service)['status'] == 'success'
    assert calls == [(['А123АА777'], '2026-10-28', '2026-10-28', True), (['А123АА777'], '2026-10-27', '2026-10-28', True)]


def test_monitoring_existing_history_not_started_twice(service, monkeypatch):
    monkeypatch.setattr(monitoring, 'configured', lambda _: True)
    monkeypatch.setattr(monitoring_history, 'job_status', lambda _: {'status': 'running'})
    monkeypatch.setattr(monitoring, 'sync', lambda _: pytest.fail('Busy source called'))
    service.start()
    state = wait(service)
    assert state['sources']['monitoring']['status'] == 'busy'
    assert state['status'] == 'partial'


def test_scheduler_starts_real_provider_job_without_browser(service, monkeypatch):
    monkeypatch.setattr(refresh, 'INTERVAL', 1)
    monkeypatch.setattr(transtrade, 'configured', lambda _: True)
    called = threading.Event()
    monkeypatch.setattr(transtrade, 'sync', lambda *_: called.set() or {'received': 0})
    service.start_scheduler()
    try:
        assert called.wait(3)
        state = wait(service)
        assert state['trigger'] == 'automatic'
        assert state['status'] == 'success'
        assert state['from'] == refresh.now().date().replace(day=1).isoformat()
    finally:
        service.stop()
        service.scheduler.join(2)


def test_endpoint_authorization_csrf_and_invalid_period(service, monkeypatch):
    app = Flask(__name__)
    app.secret_key = 'test-only'
    def auth(roles=None):
        def wrap(fn):
            @wraps(fn)
            def call(*args, **kwargs):
                if not session.get('uid'):
                    return jsonify(error='login'), 401
                if roles and session['role'] not in roles:
                    return jsonify(error='role'), 403
                if request.method == 'POST' and request.headers.get('X-CSRF-Token') != session['csrf']:
                    return jsonify(error='csrf'), 403
                return fn(*args, **kwargs)
            return call
        return wrap
    app.register_error_handler(ValueError, lambda error: (jsonify(error=str(error)), 400))
    registered = refresh.register(app, auth, service.data_dir, service.db_path, lambda: {})
    calls = []
    monkeypatch.setattr(registered, 'start', lambda *args, **kwargs: calls.append((args, kwargs)) or {'accepted': True})
    client = app.test_client()
    assert client.get('/api/refresh').status_code == 401
    with client.session_transaction() as s:
        s.update(uid=9, role='viewer', csrf='x')
    assert client.get('/api/refresh').status_code == 200
    assert client.post('/api/refresh', json={}, headers={'X-CSRF-Token': 'x'}).status_code == 403
    with client.session_transaction() as s:
        s['role'] = 'admin'
    assert client.post('/api/refresh', json={}).status_code == 403
    assert client.post('/api/refresh', json=[], headers={'X-CSRF-Token': 'x'}).status_code == 400
    assert client.post('/api/refresh', json={'from': '2026-08-01', 'to': '2026-08-31'}, headers={'X-CSRF-Token': 'x'}).status_code == 202
    assert calls == [(('2026-08-01', '2026-08-31'), {'user_id': 9})]
