import datetime as dt
import json
from pathlib import Path

from app import alerts, alertwatch


UTC = dt.timezone.utc


def test_repeated_missing_worker_observations_keep_grace_and_open_incident(tmp_path):
    at = dt.datetime(2026, 10, 30, 12, tzinfo=UTC)
    first = alertwatch.observe_once(tmp_path, at=at, deliver=False)
    assert first['incidents'] == []
    second = alertwatch.observe_once(tmp_path, at=at+dt.timedelta(seconds=60), deliver=False)
    assert second['incidents'] == []
    third = alertwatch.observe_once(tmp_path, at=at+dt.timedelta(seconds=120), deliver=False)
    assert [item['key'] for item in third['incidents']] == ['worker']
    assert third['incidents'][0]['first_seen'] == at.isoformat()
    assert third['delivery']['configured'] is False


def test_worker_failure_notification_is_sent_once_without_worker_process(tmp_path, monkeypatch):
    at = dt.datetime(2026, 10, 30, 12, tzinfo=UTC)
    config = tmp_path/'alerts-config.json'
    config.write_text(json.dumps({'enabled': True, 'channel': 'telegram'}))
    config.chmod(0o600)
    sent = []
    monkeypatch.setattr(alerts, '_send', lambda config, text: sent.append(text))
    alertwatch.observe_once(tmp_path, at=at)
    alertwatch.observe_once(tmp_path, at=at+dt.timedelta(seconds=100))
    alertwatch.observe_once(tmp_path, at=at+dt.timedelta(seconds=160))
    assert len(sent) == 1 and 'Автоматическое обновление остановилось' in sent[0]
    monkeypatch.setattr(alertwatch.autosync, 'public_status', lambda *a, **k: {
        'scheduler_expected': True, 'server_scheduler': True,
        'heartbeat_at': (at+dt.timedelta(seconds=200)).isoformat(), 'sources': {}})
    healed = alertwatch.observe_once(tmp_path, at=at+dt.timedelta(seconds=200))
    assert healed['incidents'] == []
    assert len(sent) == 2 and 'восстановлено' in sent[-1]
    alertwatch.observe_once(tmp_path, at=at+dt.timedelta(seconds=210))
    assert len(sent) == 2


def test_malformed_scheduler_state_does_not_echo_its_contents(tmp_path):
    (tmp_path/'refresh-auto.json').write_text('{upstream-secret-placeholder')
    at = dt.datetime(2026, 10, 30, 12, tzinfo=UTC)
    alertwatch.observe_once(tmp_path, at=at, deliver=False)
    view = alertwatch.observe_once(tmp_path, at=at+dt.timedelta(minutes=2), deliver=False)
    assert [item['key'] for item in view['incidents']] == ['worker']
    assert 'upstream-secret-placeholder' not in json.dumps(view)
    assert (tmp_path/'refresh-auto.json').read_text() == '{upstream-secret-placeholder'


def test_timer_is_independent_of_worker_and_does_not_run_initialization():
    root = Path(__file__).resolve().parents[1]
    service = (root/'deploy/fleet-alerts.service').read_text()
    timer = (root/'deploy/fleet-alerts.timer').read_text()
    assert '-m app.alertwatch' in service
    assert 'fleet-worker.service' not in service and 'preflight.py' not in service
    assert 'OnBootSec=30s' in timer and 'OnUnitActiveSec=60s' in timer
    assert 'WantedBy=timers.target' in timer
