import base64
import json
from decimal import Decimal

import pytest
import requests

from app import rosneft

CARDS = [{'Num': '000123', 'Rem': '<b>Car</b>', 'SName': 'В работе', 'SCode': '00', 'CardGrp': ''}]
OP = dict(Date='2026-08-31T23:59:59', Card='000123', Type=11, Value=Decimal('50.123'),
          Sum=Decimal('4000.01'), DSum=Decimal('12.34'), Price=Decimal('79.80'),
          DPrice=Decimal('0.01'), Vat=Decimal('22.00'), Contract='ISS-TEST',
          GCat='FUEL', GName='ДТ', Code='op-1', Ref='', Address='<script>test</script>')


def test_exact_decimals_local_time_card_number_and_return_preserved():
    back = {**OP, 'Code': 'op-2', 'Type': 24, 'Ref': 'op-1'}
    cards, rows = rosneft.normalize(CARDS, {'OperationList': [OP, back]}, 'ISS-TEST', '2026-08-01', '2026-08-31')
    assert cards[0]['Num'] == '000123'
    assert rows[0]['Type'] == 24 and rows[0]['Ref'] == 'op-1'
    assert rows[0]['Value'] == '50.123' and rows[0]['Sum'] == '4000.01'
    assert rows[0]['NetSum'] == '3987.67'
    assert rows[0]['Date'] == '2026-08-31T23:59:59'
    assert rows[0]['Address'] == '<script>test</script>'


@pytest.mark.parametrize('change', [dict(Value='NaN'), dict(Contract='OTHER'), dict(Date='2026-09-01T00:00:00'),
                                   dict(Date='bad'), dict(Type='11'), dict(Card=123), dict(Code=''), dict(Sum=None)])
def test_invalid_data_rejected(change):
    with pytest.raises(ValueError):
        rosneft.normalize(CARDS, {'OperationList': [{**OP, **change}]}, 'ISS-TEST', '2026-08-01', '2026-08-31')


def test_duplicate_operations_and_malformed_envelope_rejected():
    for data in ({'OperationList': [OP, OP]}, {}, [], {'OperationList': None}):
        with pytest.raises(ValueError):
            rosneft.normalize(CARDS, data, 'ISS-TEST', '2026-08-01', '2026-08-31')
    assert rosneft.normalize([], {'OperationList': []}, 'ISS-TEST', '2026-08-01', '2026-08-31') == ([], [])


@pytest.mark.parametrize('a,b', [(None, None), ('2026-01-01', '2026-02-01'), ('2026-08-31', '2026-08-01'), ('bad', '2026-08-01')])
def test_period_limit(a, b):
    with pytest.raises(ValueError):
        rosneft.period(a, b)
    assert rosneft.period('2026-08-01', '2026-08-31') == ('2026-08-01', '2026-08-31')


def setup_fake(tmp_path, monkeypatch, status=200, body=None, error=None):
    (tmp_path / 'rosneft-credentials.json').write_text(json.dumps({'login': 'test-login', 'password': 'test-secret', 'contract': 'ISS-TEST'}))
    calls = []
    class Response:
        status_code = status
        def __init__(self, url):
            self.url = url
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, *args):
            if body is not None:
                yield body
            else:
                value = CARDS if 'GetCards' in self.url else {'OperationList': [OP]}
                yield json.dumps(value, default=str).encode()
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            if error: raise error
            return Response(url)
    monkeypatch.setattr(rosneft.requests, 'Session', Session)
    return calls


def test_sync_secret_is_header_only_atomic_snapshot_no_duplicates(tmp_path, monkeypatch):
    calls = setup_fake(tmp_path, monkeypatch)
    for _ in range(2):
        rosneft.sync(tmp_path, '2026-08-01', '2026-08-31')
    saved = rosneft.snapshot(tmp_path)
    assert len(saved['rows']) == 1 and len(saved['cards']) == 1
    assert 'test-secret' not in json.dumps(saved) and 'test-login' not in json.dumps(saved)
    assert (tmp_path / 'rosneft-transactions.json').stat().st_mode & 0o777 == 0o600
    for url, kwargs in calls:
        assert url.startswith(rosneft.BASE) and '?' not in url
        assert 'test-secret' not in json.dumps(kwargs['params'])
        assert base64.b64decode(kwargs['headers']['RnCard-Identity-Account-Pass']) == b'test-secret'
        assert kwargs['allow_redirects'] is False
    assert calls[1][1]['params']['end'] == '2026-08-31T23:59:59'


@pytest.mark.parametrize('status,body,error', [(403, None, None), (302, None, None), (429, None, None),
    (200, b'<html>Login</html>', None), (200, b'{}', None),
    (200, None, requests.Timeout('secret in request URL'))])
def test_failure_preserves_previous_snapshot_and_sanitizes_errors(tmp_path, monkeypatch, status, body, error):
    setup_fake(tmp_path, monkeypatch, status, body, error)
    path = tmp_path / 'rosneft-transactions.json'; path.write_text('{"previous":true}')
    with pytest.raises(ValueError) as caught:
        rosneft.sync(tmp_path, '2026-08-01', '2026-08-31')
    assert path.read_text() == '{"previous":true}'
    assert 'secret' not in str(caught.value)
    assert not rosneft.LOCK.locked()


def test_mutating_methods_and_overlapping_sync_are_blocked(tmp_path):
    with pytest.raises(ValueError):
        rosneft.read(None, {}, 'v2/BlockCard')
    rosneft.LOCK.acquire()
    try:
        with pytest.raises(ValueError):
            rosneft.sync(tmp_path, '2026-08-01', '2026-08-31')
    finally:
        rosneft.LOCK.release()


def test_oversize_response_preserves_snapshot(tmp_path, monkeypatch):
    setup_fake(tmp_path, monkeypatch, body=b'123456')
    monkeypatch.setattr(rosneft, 'MAX_BYTES', 5)
    with pytest.raises(ValueError, match='слишком большой'):
        rosneft.sync(tmp_path, '2026-08-01', '2026-08-31')
    assert rosneft.snapshot(tmp_path) is None
