import copy
import datetime as dt
import fcntl
import json
import os
import ssl

import pytest

from app import alerts


T0 = dt.datetime(2026, 10, 30, 9, tzinfo=dt.timezone.utc)


def stamp(minutes=0, seconds=0):
    return T0+dt.timedelta(minutes=minutes, seconds=seconds)


def status(at=T0, *, success=T0, source_status='success', **extra):
    source = {'status': source_status, 'last_success_at': success.isoformat() if success else None,
              'last_attempt_at': at.isoformat(), **extra}
    return {'scheduler_expected': True, 'server_scheduler': True, 'heartbeat_at': at.isoformat(),
            'started_at': T0.isoformat(), 'sources': {'transtrade': source}}


def config(folder, **values):
    path = folder/alerts.CONFIG_NAME
    path.write_text(json.dumps(values))
    path.chmod(0o600)


def enabled(folder):
    config(folder, enabled=True, channel='telegram', telegram={'bot_token': '123:synthetic-token', 'chat_id': '1234'})


def test_readonly_healthy_view_creates_nothing(tmp_path):
    view = alerts.current(tmp_path, status(), at=T0)
    assert not view['incidents'] and view['delivery']['status'] == 'disabled'
    assert list(tmp_path.iterdir()) == []


def test_short_failures_are_quiet_and_recovery_never_alerts(tmp_path):
    for minute in (0, 5, 14):
        view = alerts.observe(tmp_path, status(stamp(minute), source_status='error'), at=stamp(minute))
        assert not view['incidents']
    view = alerts.observe(tmp_path, status(stamp(14), success=stamp(14)), at=stamp(14))
    assert not view['incidents'] and not view['recent']


def test_long_failure_is_durable_deduplicated_and_resolves(tmp_path):
    alerts.observe(tmp_path, status(source_status='error'), at=T0)
    first = alerts.observe(tmp_path, status(stamp(15), source_status='error'), at=stamp(15))
    assert len(first['incidents']) == 1
    ident = first['incidents'][0]['id']
    # A later observe call loads all its state from disk, like a restarted worker.
    second = alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    assert second['incidents'][0]['id'] == ident and not second['recent']
    recovered = alerts.observe(tmp_path, status(stamp(21), success=stamp(21)), at=stamp(21))
    assert not recovered['incidents']
    assert recovered['recent'][0]['id'] == ident
    assert recovered['recent'][0]['status'] == 'resolved'
    assert len(alerts.observe(tmp_path, status(stamp(22), success=stamp(22)), at=stamp(22))['recent']) == 1


def test_attempts_without_first_success_do_not_reset_age(tmp_path):
    for minute in (0, 5, 10):
        assert not alerts.observe(tmp_path, status(stamp(minute), success=None), at=stamp(minute))['incidents']
    assert len(alerts.observe(tmp_path, status(stamp(15), success=None), at=stamp(15))['incidents']) == 1


def test_old_success_is_stale_even_when_snapshot_says_success(tmp_path):
    view = alerts.current(tmp_path, status(stamp(20)), at=stamp(20))
    assert [row['key'] for row in view['incidents']] == ['source:transtrade']


def test_worker_staleness_is_computed_without_worker_or_writes(tmp_path):
    state = status(stamp(3), success=stamp(3))
    state['heartbeat_at'] = T0.isoformat()
    view = alerts.current(tmp_path, state, at=stamp(3))
    assert view['incidents'][0]['key'] == 'worker'
    assert view['incidents'][0]['severity'] == 'error'
    assert list(tmp_path.iterdir()) == []


def test_missing_worker_after_start_grace_and_disabled_scheduler(tmp_path):
    state = status(stamp(3), success=stamp(3))
    state.update(server_scheduler=False, heartbeat_at=None)
    assert alerts.current(tmp_path, state, at=stamp(3))['incidents'][0]['key'] == 'worker'
    state['scheduler_expected'] = False
    assert not alerts.current(tmp_path, state, at=stamp(3))['incidents']


def test_unconfigured_sources_do_not_alert(tmp_path):
    state = status(stamp(30), success=None, source_status='unconfigured')
    assert not alerts.observe(tmp_path, state, at=stamp(30))['incidents']


def test_backlog_is_separate_from_failures(tmp_path):
    state = status(catchup={'pending_days': 11, 'error': 'do not copy this'})
    view = alerts.observe(tmp_path, state, at=T0)
    assert not view['incidents']
    assert view['backlog'] == [{'source': 'transtrade', 'name': 'ТрансТрейд', 'pending_days': 11,
                               'message': 'Догружаются пропущенные данные: 11 дн.'}]


def test_outbound_only_open_and_recovery_with_sanitized_content(tmp_path, monkeypatch):
    enabled(tmp_path)
    sent = []
    monkeypatch.setattr(alerts, '_send', lambda config, text: sent.append(text))
    failed = status(stamp(20), source_status='error', message='api_key=DO-NOT-LEAK',
                    error='password=OTHER-SECRET', account='customer-name')
    view = alerts.observe(tmp_path, failed, at=stamp(20))
    assert len(sent) == 1 and view['delivery']['status'] == 'sent'
    alerts.observe(tmp_path, status(stamp(25), source_status='error'), at=stamp(25))
    assert len(sent) == 1
    alerts.observe(tmp_path, status(stamp(26), success=stamp(26)), at=stamp(26))
    assert len(sent) == 2 and 'восстановлено' in sent[-1]
    all_content = json.dumps(view, ensure_ascii=False)+(tmp_path/alerts.STATE_NAME).read_text()+''.join(sent)
    for secret in ('DO-NOT-LEAK', 'OTHER-SECRET', 'customer-name', 'synthetic-token'):
        assert secret not in all_content


def test_failed_delivery_persists_and_backs_off_without_leaking_exception(tmp_path, monkeypatch):
    enabled(tmp_path)
    calls = []
    def failing(config, text):
        calls.append(text)
        raise RuntimeError('https://api.telegram.org/bot123:SECRET/sendMessage password=TOKEN')
    monkeypatch.setattr(alerts, '_send', failing)
    first = alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    assert first['delivery']['status'] == 'error' and first['delivery']['pending'] == 1
    alerts.observe(tmp_path, status(stamp(20, 30), source_status='error'), at=stamp(20, 30))
    assert len(calls) == 1
    alerts.observe(tmp_path, status(stamp(21), source_status='error'), at=stamp(21))
    assert len(calls) == 2
    alerts.observe(tmp_path, status(stamp(22), source_status='error'), at=stamp(22))
    assert len(calls) == 2
    saved = (tmp_path/alerts.STATE_NAME).read_text()
    assert 'SECRET' not in saved and 'TOKEN' not in saved and 'telegram.org' not in saved
    monkeypatch.setattr(alerts, '_send', lambda config, text: calls.append(text))
    done = alerts.observe(tmp_path, status(stamp(23), source_status='error'), at=stamp(23))
    assert len(calls) == 3 and done['delivery']['pending'] == 0


def test_recovery_cancels_an_undelivered_failure(tmp_path, monkeypatch):
    enabled(tmp_path)
    calls = []
    monkeypatch.setattr(alerts, '_send', lambda config, text: calls.append(text))
    first = alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20), deliver=False)
    assert first['delivery']['pending'] == 1 and not calls
    recovered = alerts.observe(tmp_path, status(stamp(21), success=stamp(21)), at=stamp(21))
    assert recovered['delivery']['pending'] == 0 and not calls


def test_new_failure_supersedes_delayed_old_recovery(tmp_path, monkeypatch):
    enabled(tmp_path)
    calls = []
    monkeypatch.setattr(alerts, '_send', lambda config, text: calls.append(text))
    alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    recovered = alerts.observe(tmp_path, status(stamp(21), success=stamp(21)), at=stamp(21), deliver=False)
    assert recovered['delivery']['pending'] == 1
    alerts.observe(tmp_path, status(stamp(40), success=stamp(21), source_status='error'), at=stamp(40))
    assert len(calls) == 2 and 'восстановлено' not in calls[-1]
    assert not json.loads((tmp_path/alerts.STATE_NAME).read_text())['outbox']


def test_disabling_source_is_not_reported_as_recovery(tmp_path, monkeypatch):
    enabled(tmp_path)
    calls = []
    monkeypatch.setattr(alerts, '_send', lambda config, text: calls.append(text))
    alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    view = alerts.observe(tmp_path, status(stamp(21), source_status='unconfigured'), at=stamp(21))
    assert len(calls) == 1 and not view['incidents']
    assert view['recent'][0]['status'] == 'closed'


def test_missing_source_status_does_not_claim_recovery(tmp_path, monkeypatch):
    enabled(tmp_path)
    calls = []
    monkeypatch.setattr(alerts, '_send', lambda config, text: calls.append(text))
    alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    partial = status(stamp(21))
    partial['sources'] = {}
    view = alerts.observe(tmp_path, partial, at=stamp(21))
    assert len(calls) == 1 and len(view['incidents']) == 1


def test_disabled_delivery_never_calls_network_then_enable_sends_current_issue(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(alerts, '_send', lambda config, text: calls.append(text))
    alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    assert not calls
    enabled(tmp_path)
    alerts.observe(tmp_path, status(stamp(21), source_status='error'), at=stamp(21))
    assert len(calls) == 1


def test_corrupted_state_is_visible_and_preserved(tmp_path, monkeypatch):
    path = tmp_path/alerts.STATE_NAME
    path.write_text('{broken')
    enabled(tmp_path)
    monkeypatch.setattr(alerts, '_send', lambda *_: pytest.fail('No send from damaged state'))
    view = alerts.observe(tmp_path, status(stamp(20)), at=stamp(20))
    assert view['storage_error'] == alerts.STORAGE_ERROR
    assert path.read_text() == '{broken'


def test_atomic_state_and_private_permissions(tmp_path, monkeypatch):
    alerts.observe(tmp_path, status(), at=T0)
    path = tmp_path/alerts.STATE_NAME
    before = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    def fail(*_):
        raise OSError('synthetic full disk')
    monkeypatch.setattr(alerts.os, 'replace', fail)
    with pytest.raises(OSError):
        alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('.alerts-*'))


@pytest.mark.parametrize('bad', ['permissions', 'json', 'channel'])
def test_invalid_config_cannot_send(tmp_path, monkeypatch, bad):
    enabled(tmp_path)
    path = tmp_path/alerts.CONFIG_NAME
    if bad == 'permissions':
        path.chmod(0o644)
    elif bad == 'json':
        path.write_text('[not json')
    else:
        config(tmp_path, enabled=True, channel='http')
    monkeypatch.setattr(alerts, '_send', lambda *_: pytest.fail('Invalid config must not send'))
    view = alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    assert view['delivery']['error'] == alerts.CONFIG_ERROR
    assert len(view['incidents']) == 1


def test_telegram_delivery_keeps_tls_redirect_guard_and_fixed_endpoint(monkeypatch):
    calls = []
    class Response:
        status_code = 200
        closed = False
        def json(self):
            return {'ok': True}
        def close(self):
            self.closed = True
    response = Response()
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response
    monkeypatch.setattr(alerts.requests, 'post', post)
    alerts._send({'channel': 'telegram', 'telegram': {'bot_token': '123:synthetic', 'chat_id': '-10'}}, 'safe message')
    assert calls[0][0] == 'https://api.telegram.org/bot123:synthetic/sendMessage'
    assert calls[0][1]['allow_redirects'] is False
    assert calls[0][1].get('verify', True) is True
    assert calls[0][1]['json'] == {'chat_id': '-10', 'text': 'safe message', 'disable_web_page_preview': True}
    assert response.closed


def test_smtp_uses_verified_tls_and_explicit_envelope(monkeypatch):
    calls = []
    class SMTP:
        def __init__(self, host, port, **kwargs):
            assert host == 'smtp.example.invalid' and port == 465
            assert kwargs['context'].verify_mode == ssl.CERT_REQUIRED
            assert kwargs['context'].check_hostname
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def login(self, username, password):
            assert username == 'account' and password == 'synthetic-secret'
        def send_message(self, message, **kwargs):
            calls.append((message, kwargs))
    monkeypatch.setattr(alerts.smtplib, 'SMTP_SSL', SMTP)
    monkeypatch.setenv('FLEET_TEST_SMTP_SECRET', 'synthetic-secret')
    alerts._send({'channel': 'smtp', 'smtp': {'host': 'smtp.example.invalid', 'from': 'fleet@example.invalid',
                 'to': ['owner@example.invalid'], 'username': 'account', 'password_env': 'FLEET_TEST_SMTP_SECRET'}}, 'safe message')
    assert calls[0][1] == {'from_addr': 'fleet@example.invalid', 'to_addrs': ['owner@example.invalid']}
    assert 'synthetic-secret' not in str(calls[0][0])


def test_another_observer_holds_lock_no_duplicate_dispatch(tmp_path, monkeypatch):
    enabled(tmp_path)
    monkeypatch.setattr(alerts, '_send', lambda *_: pytest.fail('Contended lock must not send'))
    with (tmp_path/'alerts.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        view = alerts.observe(tmp_path, status(stamp(20), source_status='error'), at=stamp(20))
    assert len(view['incidents']) == 1
    assert not (tmp_path/alerts.STATE_NAME).exists()


def test_custom_stale_threshold_changes_delay_without_sensitive_settings_in_view(tmp_path):
    config(tmp_path, stale_after_seconds=1800, smtp={'password': 'not-a-real-secret'})
    assert not alerts.observe(tmp_path, status(stamp(20)), at=stamp(20))['incidents']
    view = alerts.observe(tmp_path, status(stamp(31)), at=stamp(31))
    assert len(view['incidents']) == 1
    assert 'not-a-real-secret' not in json.dumps(view)
