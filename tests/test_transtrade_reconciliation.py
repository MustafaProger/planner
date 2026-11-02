from tests.test_workspace import confirmation
"""History reconciliation against isolated SQLite fixtures and synthetic API reads."""
import copy
import datetime as dt
import json
import sqlite3
from itertools import islice

import pytest

from app import transtrade as t, workspace as w
from tests.test_workspace import source, c, ADMIN
from tests.test_transtrade import raw


@pytest.fixture
def isolated(tmp_path, source, monkeypatch):
    db = tmp_path / 'fleet.sqlite'
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        w.initialize(connection, source)
    monkeypatch.setattr(t, 'credentials', lambda _: {'api_key': 'synthetic', 'api_user_id': 1})
    class Transport:
        def close(self):
            pass
    monkeypatch.setattr(t, 'transport', lambda _: Transport())
    return tmp_path, db


def read_records(db):
    with sqlite3.connect(db) as connection:
        return connection.execute('select id,kind,body,revision,deleted from records order by id').fetchall()


def dataset(db):
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        return w.dataset(connection)


def install_source(monkeypatch, full, by_id=None):
    calls = []
    def fetch(config, params):
        calls.append(dict(params))
        config['_response_meta'] = {'response_bytes': 1234, 'seconds': .1}
        return copy.deepcopy(full if not params else (by_id or {}).get(params['OrderId'], []))
    monkeypatch.setattr(t, 'get_orders', fetch)
    return calls


def test_full_scope_discovers_hidden_orders_preserves_excel_and_repeats(isolated, monkeypatch):
    folder, db = isolated
    ancient = dict(raw('5'), BeginDateTime='2020-01-01 08:00:00', EndDateTime='2020-01-01 12:00:00')
    calls = install_source(monkeypatch, [raw(), raw('4'), ancient], {2: [raw('2')], 3: [raw('3')]})
    first = t.reconcile(folder, db)
    assert first['status'] == 'success'
    assert first['unfiltered_received'] == 3 and first['processed'] == 4
    assert first['discovered_by_id'] == 2 and first['gap_pending'] == 0
    assert calls == [{}, {'OrderId': 3}, {'OrderId': 2}]
    trips = {r['id']: r for r in dataset(db)['trips']}
    assert set(trips) == {'1', '2', '3', '4'}
    assert trips['1']['legacy_snapshot']['km'] == 90
    assert all(r['km'] is None for r in trips.values())
    assert trips['2']['api_list_omitted'] and trips['3']['api_list_omitted']
    before = read_records(db)
    second = t.reconcile(folder, db, force=True)
    assert second['created'] == second['updated'] == 0
    assert second['unchanged'] == 4
    assert read_records(db) == before
    assert second['complete'] is False


def test_known_order_moved_before_scope_is_refreshed_without_importing_ancient_period(isolated, monkeypatch):
    folder, db = isolated
    moved = dict(raw(), BeginDateTime='2026-07-01 08:00:00', EndDateTime='2026-07-01 12:00:00')
    unrelated = dict(raw('2'), BeginDateTime='2026-07-02 08:00:00', EndDateTime='2026-07-02 12:00:00')
    install_source(monkeypatch, [moved, unrelated])
    result = t.reconcile(folder, db)
    assert result['status'] == 'success' and result['scope_start'] == '2026-08-01'
    assert [(r['id'], r['date']) for r in dataset(db)['trips']] == [('1', '2026-07-01')]
    assert t.reconcile(folder, db, force=True)['scope_start'] == '2026-08-01'


def test_full_result_never_replaces_period_status(isolated, monkeypatch):
    folder, db = isolated
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        period = t.apply(connection, [raw()], '2026-08-01', '2026-08-31')
        runs = connection.execute("select body from workspace_meta where key='transtrade_runs'").fetchone()[0]
    install_source(monkeypatch, [raw(), raw('2')])
    assert t.reconcile(folder, db)['status'] == 'success'
    with sqlite3.connect(db) as connection:
        assert t.status(connection) == period
        assert connection.execute("select body from workspace_meta where key='transtrade_runs'").fetchone()[0] == runs


@pytest.mark.parametrize('failure', ['duplicate', 'invalid', 'wrong_id', 'empty', 'direct_error'])
def test_invalid_history_is_atomic_and_keeps_existing_rows(isolated, monkeypatch, failure):
    folder, db = isolated
    before = read_records(db)
    full = [dict(raw(), ClientSum='9999'), raw('3')]
    by_id = {2: [raw('2')]}
    if failure == 'duplicate':
        full.append(raw('3'))
    elif failure == 'invalid':
        full.append(dict(raw('4'), BeginDateTime=''))
    elif failure == 'wrong_id':
        by_id[2] = [raw('999')]
    elif failure == 'empty':
        full = []
    calls = install_source(monkeypatch, full, by_id)
    if failure == 'direct_error':
        def fetch(_, params):
            if params:
                raise ValueError('synthetic failure')
            return full
        monkeypatch.setattr(t, 'get_orders', fetch)
    result = t.reconcile(folder, db)
    assert result['status'] == 'error'
    assert read_records(db) == before
    with sqlite3.connect(db) as connection:
        assert not connection.execute("select 1 from sqlite_master where name='transtrade_orders'").fetchone()


def test_disappeared_order_is_kept_even_if_direct_id_empty(isolated, monkeypatch):
    folder, db = isolated
    install_source(monkeypatch, [raw('2')])
    result = t.reconcile(folder, db)
    rows = {r['id']: r for r in dataset(db)['trips']}
    assert result['status'] == 'success' and result['missing'] == 1
    assert rows['1']['api_missing'] and rows['1']['revenue'] == 900
    assert rows['1']['km'] == 90  # Unrefreshed Excel remains explicitly Excel.
    assert not rows['1'].get('cancelled')


def test_full_apply_empty_response_preserves_rows(c):
    before = w.dataset(c)['trips'][0]
    result = t.apply(c, [], '2026-08-01', '2026-08-31', full=True)
    after = w.dataset(c)['trips'][0]
    assert result['missing'] == 1 and after['api_missing']
    assert after['record_id'] == before['record_id'] and after['revenue'] == before['revenue']


def test_full_preserves_manual_deleted_and_category_override(isolated, monkeypatch):
    folder, db = isolated
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        existing = w.dataset(connection)['trips'][0]
        w.edit_record(connection, existing['record_id'], {'revision': existing['revision'], 'category': 'Сервис'}, ADMIN)
        t.apply(connection, [raw(), raw('2'), raw('3')], '2026-08-01', '2026-08-31')
        rows = {r['id']: r for r in w.dataset(connection)['trips']}
        edited = dict(rows['2'], origin='manual', user_edited=True, revenue=12345)
        connection.execute('update records set body=? where id=?', (w.dump(edited), rows['2']['record_id']))
        connection.execute('update records set deleted=1 where id=?', (rows['3']['record_id'],))
        protected = connection.execute('select id,body,revision,deleted from records where id in (?,?) order by id',
                                       (rows['2']['record_id'], rows['3']['record_id'])).fetchall()
        protected = [tuple(r) for r in protected]
    install_source(monkeypatch, [dict(raw(), ClientSum='500'), raw('2'), raw('3')])
    result = t.reconcile(folder, db)
    assert result['conflicts'] == 2
    with sqlite3.connect(db) as connection:
        after = connection.execute('select id,body,revision,deleted from records where id in (?,?) order by id',
                                   (rows['2']['record_id'], rows['3']['record_id'])).fetchall()
        assert after == protected
    assert next(r for r in dataset(db)['trips'] if r['id'] == '1')['category'] == 'Сервис'


def test_source_absence_does_not_mutate_user_edited_or_deleted_body(c):
    t.apply(c, [raw(), raw('2')], '2026-08-01', '2026-08-31')
    rows = {r['id']: r for r in w.dataset(c)['trips']}
    edited = dict(rows['1'], user_edited=True)
    c.execute('update records set body=? where id=?', (w.dump(edited), rows['1']['record_id']))
    c.execute('update records set deleted=1 where id=?', (rows['2']['record_id'],))
    before = [tuple(r) for r in c.execute("select id,body,revision,deleted from records where kind='trips' order by id")]
    t.apply(c, [], '2026-08-01', '2026-08-31', full=True)
    assert [tuple(r) for r in c.execute("select id,body,revision,deleted from records where kind='trips' order by id")] == before


def test_move_into_current_period_invalidates_old_and_new_coverage(c):
    for month in ('08', '09'):
        w.save_extra(c, 'coverage', confirmation(c, {'start': f'2026-{month}-01', 'end': f'2026-{month}-28',
                                   'source': 'trips', 'complete': True}), ADMIN)
    moved = dict(raw(), BeginDateTime='2026-09-01 08:00:00', EndDateTime='2026-09-01 12:00:00')
    t.apply(c, [moved], '2026-09-01', '2026-09-30')
    assert all(not row['complete'] for row in w.dataset(c)['coverage'])


def test_success_due_and_error_backoff_survive_new_call(isolated, monkeypatch):
    folder, db = isolated
    calls = install_source(monkeypatch, [raw()])
    first = t.reconcile(folder, db)
    assert first['status'] == 'success'
    delta = dt.datetime.fromisoformat(first['next_attempt_at']) - dt.datetime.fromisoformat(first['last_success_at'])
    assert dt.timedelta(hours=24) <= delta < dt.timedelta(hours=24, seconds=5)
    assert t.reconcile(folder, db)['status'] == 'skipped'
    assert calls == [{}]
    def fail(*_):
        raise ValueError('synthetic unavailable')
    monkeypatch.setattr(t, 'get_orders', fail)
    failed = t.reconcile(folder, db, force=True)
    assert failed['status'] == 'error' and failed['last_success_at'] == first['last_success_at']
    delta = dt.datetime.fromisoformat(failed['next_attempt_at']) - dt.datetime.fromisoformat(failed['attempted_at'])
    assert dt.timedelta(hours=1) <= delta < dt.timedelta(hours=1, seconds=5)
    skipped = t.reconcile(folder, db)
    assert skipped['status'] == 'skipped' and skipped['error'] == 'synthetic unavailable'
    assert skipped['last_success_at'] == first['last_success_at']


def test_gap_checks_are_bounded_and_cursor_rotates(isolated, monkeypatch):
    folder, db = isolated
    monkeypatch.setattr(t, 'MAX_ID_CHECKS', 2)
    calls = install_source(monkeypatch, [raw(), raw('8')])
    for _ in range(3):
        result = t.reconcile(folder, db, force=True)
        assert result['status'] == 'success' and result['gap_checks'] == 2
    assert [call['OrderId'] for call in calls if call] == [7, 6, 5, 4, 3, 2]


def test_known_and_gap_queues_both_progress_when_time_budget_expires(isolated, monkeypatch):
    folder, db = isolated
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        t.apply(connection, [raw(), raw('2'), raw('3')], '2026-08-01', '2026-08-31')
    monkeypatch.setattr(t, 'MAX_ID_CHECKS', 6)
    monkeypatch.setattr(t, 'MAX_RECONCILE_SECONDS', 2.1)
    clock = [0]
    monkeypatch.setattr(t.time, 'monotonic', lambda: clock[0])
    calls = []
    def fetch(_, params):
        if not params:
            return [raw('4'), raw('9')]
        calls.append(params['OrderId'])
        clock[0] += 1
        return []
    monkeypatch.setattr(t, 'get_orders', fetch)
    for _ in range(2):
        clock[0] = 0
        result = t.reconcile(folder, db, force=True)
        assert result['status'] == 'success'
        assert result['gap_checks'] == 2 and result['known_id_checks'] == 1
        assert result['known_pending'] == 2
    assert calls == [8, 3, 7, 6, 2, 5]


def test_unqueried_known_orders_are_not_labelled_missing_when_queue_is_capped(isolated, monkeypatch):
    folder, db = isolated
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        t.apply(connection, [raw(), raw('2'), raw('3')], '2026-08-01', '2026-08-31')
    before = {r['id']: r for r in dataset(db)['trips']}
    monkeypatch.setattr(t, 'MAX_ID_CHECKS', 2)
    calls = install_source(monkeypatch, [raw('4')])
    result = t.reconcile(folder, db, force=True)
    after = {r['id']: r for r in dataset(db)['trips']}
    assert result['status'] == 'success' and result['known_pending'] == 2
    assert calls == [{}, {'OrderId': 3}]
    assert after['3']['api_missing']
    assert after['1'] == before['1'] and after['2'] == before['2']


def test_interrupted_history_during_backoff_remains_visible_as_error(isolated, monkeypatch):
    folder, db = isolated
    now = dt.datetime.now(t.MSK)
    previous = {'status': 'running', 'next_attempt_at': (now + dt.timedelta(minutes=20)).isoformat(),
                'last_success_at': (now - dt.timedelta(days=1)).isoformat()}
    with sqlite3.connect(db) as connection:
        t.save_reconciliation(connection, previous)
    monkeypatch.setattr(t, 'get_orders', lambda *_: pytest.fail('Backoff must not call the provider'))
    result = t.reconcile(folder, db)
    assert result['status'] == 'skipped' and 'прервана' in result['error']
    assert result['last_success_at'] == previous['last_success_at']
    with sqlite3.connect(db) as connection:
        assert t.reconciliation_status(connection)['status'] == 'error'


def test_sparse_id_ranges_do_not_materialize_all_holes():
    ranges = t.gap_ranges({'1', '1000000000000'})
    assert ranges == [(2, 999999999999)]
    assert list(islice(t.rotate_gaps(ranges, 1000000000000), 3)) == [999999999999, 999999999998, 999999999997]


def test_busy_reconciliation_and_period_do_not_clobber_status(isolated, monkeypatch):
    folder, db = isolated
    install_source(monkeypatch, [raw()])
    t.reconcile(folder, db)
    with sqlite3.connect(db) as connection:
        previous = t.reconciliation_status(connection)
        t.save_status(connection, {'status': 'success', 'received': 1})
    with t.sync_lock(folder):
        assert t.reconcile(folder, db, force=True)['status'] == 'busy'
        with pytest.raises(t.BusyError):
            t.sync(folder, db, '2026-08-01', '2026-08-31')
    with sqlite3.connect(db) as connection:
        assert t.reconciliation_status(connection) == previous
        assert t.status(connection) == {'status': 'success', 'received': 1}


def test_automatic_period_uses_one_query_but_still_recovers_known_id(isolated, monkeypatch):
    folder, db = isolated
    calls = []
    def fetch(_, params):
        calls.append(params)
        return [raw()] if params == {'OrderId': 1} else []
    monkeypatch.setattr(t, 'get_orders', fetch)
    result = t.sync(folder, db, '2026-08-01', '2026-08-31', verify_days=False)
    assert calls == [{'FromOrderDate': '2026-08-01', 'ToOrderDate': '2026-08-31'}, {'OrderId': 1}]
    assert result['recovered_by_id'] == 1


@pytest.mark.parametrize('failure', ['duplicate', 'outside_period'])
def test_fast_period_still_rejects_invalid_response_atomically(isolated, monkeypatch, failure):
    folder, db = isolated
    rows = [raw(), raw()] if failure == 'duplicate' else [dict(raw(), BeginDateTime='2026-09-01 08:00:00')]
    monkeypatch.setattr(t, 'get_orders', lambda *_: rows)
    before = read_records(db)
    with pytest.raises(ValueError):
        t.sync(folder, db, '2026-08-01', '2026-08-31', verify_days=False)
    assert read_records(db) == before


class StreamResponse:
    status_code = 200
    def __init__(self, body):
        self.body, self.closed = body, False
    def iter_content(self, _):
        yield self.body
    def close(self):
        self.closed = True


def test_stream_limit_closes_response_and_rejects_before_decode(monkeypatch):
    response = StreamResponse(b'x' * 11)
    monkeypatch.setattr(t.requests, 'post', lambda *a, **k: response)
    monkeypatch.setattr(t, 'MAX_RESPONSE_BYTES', 10)
    with pytest.raises(ValueError, match='лимит'):
        t.get_orders({'api_key': 'synthetic', 'api_user_id': 1}, {})
    assert response.closed


def test_stream_interruption_and_malformed_json_are_redacted(monkeypatch):
    response = StreamResponse(b'{broken')
    monkeypatch.setattr(t.requests, 'post', lambda *a, **k: response)
    with pytest.raises(ValueError, match='не JSON'):
        t.get_orders({'api_key': 'synthetic', 'api_user_id': 1}, {})
    assert response.closed
    class Interrupted(StreamResponse):
        def iter_content(self, _):
            yield b'{'
            raise t.requests.exceptions.ChunkedEncodingError('secret synthetic')
    interrupted = Interrupted(b'')
    monkeypatch.setattr(t.requests, 'post', lambda *a, **k: interrupted)
    with pytest.raises(ValueError) as failure:
        t.get_orders({'api_key': 'synthetic', 'api_user_id': 1}, {})
    assert 'synthetic' not in str(failure.value) and interrupted.closed
