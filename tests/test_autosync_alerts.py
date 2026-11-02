"""Regression checks at the durable scheduler / incident boundary."""
import datetime as dt
import json

from app import alerts, autosync, health


def setup_status(monkeypatch):
    clock = [dt.datetime(2026, 10, 30, 12, tzinfo=autosync.MSK)]
    old = clock[0]-dt.timedelta(minutes=20)
    state = {'version': 1, 'started_at': old.isoformat(), 'tasks': {}}
    for source in autosync.NAMES:
        for kind in ('current', 'history'):
            state['tasks'][source+':'+kind] = {'status': 'unconfigured'}
    current = state['tasks']['transtrade:current']
    current.update(status='success', last_success_at=clock[0].isoformat())
    history = state['tasks']['transtrade:history']
    history.update(status='error', error_since=old.isoformat(), message='Synthetic history unavailable')
    monkeypatch.setattr(autosync, 'read_state', lambda _: state)
    monkeypatch.setattr(autosync, 'now', lambda: clock[0])
    monkeypatch.setattr(health, 'read_worker_health', lambda _: {'healthy': True, 'heartbeat_at': clock[0].isoformat()})
    return clock, current, history


def observe(folder, clock):
    return alerts.observe(folder, autosync.public_status(folder), at=clock[0])


def test_history_incident_survives_retry_and_resolves_only_after_success(tmp_path, monkeypatch):
    clock, current, history = setup_status(monkeypatch)
    config = tmp_path/alerts.CONFIG_NAME
    config.write_text(json.dumps({'enabled': True, 'channel': 'telegram',
                                 'telegram': {'bot_token': '123:synthetic', 'chat_id': '1234'}}))
    config.chmod(0o600)
    sent = []
    monkeypatch.setattr(alerts, '_send', lambda config, message: sent.append(message))
    first = observe(tmp_path, clock)
    assert len(first['incidents']) == 1 and len(sent) == 1
    ident = first['incidents'][0]['id']
    for phase in ('running', 'interrupted', 'error'):
        clock[0] += dt.timedelta(minutes=1)
        current['last_success_at'] = clock[0].isoformat()
        history['status'] = phase
        public = autosync.public_status(tmp_path)
        assert public['sources']['transtrade']['status'] == 'error'
        during = observe(tmp_path, clock)
        assert during['incidents'][0]['id'] == ident
        assert not during['recent'] and len(sent) == 1
    clock[0] += dt.timedelta(minutes=1)
    current['last_success_at'] = clock[0].isoformat()
    history.update(status='success', error_since=None, last_success_at=clock[0].isoformat())
    final = observe(tmp_path, clock)
    assert not final['incidents']
    assert final['recent'][0]['id'] == ident and final['recent'][0]['status'] == 'resolved'
    assert len(sent) == 2 and 'восстановлено' in sent[-1]


def test_disconnected_current_source_dominates_old_history_error(tmp_path, monkeypatch):
    clock, current, history = setup_status(monkeypatch)
    first = observe(tmp_path, clock)
    assert len(first['incidents']) == 1
    current['status'] = 'unconfigured'
    public = autosync.public_status(tmp_path)
    assert set(public['sources']) == set(autosync.NAMES)
    assert public['sources']['transtrade']['status'] == 'unconfigured'
    final = observe(tmp_path, clock)
    assert not final['incidents']
    assert final['recent'][0]['status'] == 'closed'


def test_unconfigured_history_does_not_resurrect_its_old_failure(tmp_path, monkeypatch):
    clock, current, history = setup_status(monkeypatch)
    history['status'] = 'unconfigured'  # error_since remains in persisted metadata.
    public = autosync.public_status(tmp_path)
    assert public['sources']['transtrade']['status'] == 'success'
    assert not alerts.current(tmp_path, public, at=clock[0])['incidents']
