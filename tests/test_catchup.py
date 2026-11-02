import json
import sqlite3
import subprocess
import sys

import pytest

from app import catchup


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.delenv('FLEET_SYNC_FROM', raising=False)
    db = tmp_path/'fleet.sqlite'
    with sqlite3.connect(db) as connection:
        connection.execute('create table records(id text,kind text,body text,deleted integer default 0)')
        connection.execute('create table workspace_meta(key text primary key,body text)')
        connection.execute("insert into records(id,kind,body) values('trip','trips',?)",
                           (json.dumps({'date': '2026-08-01'}),))
        connection.execute("insert into records(id,kind,body) values('plan','plans',?)",
                           (json.dumps({'date': '2020-01-01'}),))
    return tmp_path, db


def save_meta(db, key, value):
    with sqlite3.connect(db) as connection:
        connection.execute('insert or replace into workspace_meta values(?,?)', (key, json.dumps(value)))


def saved(folder):
    return json.loads((folder/catchup.STATE_FILE).read_text())


def test_initial_scope_ignores_plans_and_missing_days_are_bounded(workspace):
    folder, db = workspace
    result = catchup.plan(folder, db, 'transtrade', today='2026-08-12')
    assert result == {'scope_start': '2026-08-01', 'target_end': '2026-08-11',
                      'from': '2026-08-01', 'to': '2026-08-07', 'pending_days': 11}
    assert (folder/catchup.STATE_FILE).stat().st_mode & 0o777 == 0o600
    assert (folder/'refresh-coverage.lock').stat().st_mode & 0o777 == 0o600
    assert '2020-01-01' not in (folder/catchup.STATE_FILE).read_text()


def test_success_survives_restart_failure_does_not_advance_and_gaps_stay_contiguous(workspace):
    folder, db = workspace
    first = catchup.plan(folder, db, 'transtrade', today='2026-08-10')
    # No mark on an interrupted/failed query: another process gets the same job.
    assert catchup.plan(str(folder), str(db), 'transtrade', today='2026-08-10') == first
    catchup.mark_success(folder, 'transtrade', '2026-08-01', '2026-08-03', at='2026-08-10T10:00:00+03:00')
    catchup.mark_success(folder, 'transtrade', '2026-08-06', '2026-08-06', at='2026-08-10T10:00:00+03:00')
    remaining = catchup.plan(folder, db, 'transtrade', today='2026-08-10')
    assert (remaining['from'], remaining['to'], remaining['pending_days']) == ('2026-08-04', '2026-08-05', 5)
    catchup.mark_success(folder, 'transtrade', '2026-08-04', '2026-08-09', at='2026-08-10T10:00:00+03:00')
    assert catchup.plan(folder, db, 'transtrade', today='2026-08-10')['from'] is None
    assert catchup.plan(folder, db, 'transtrade', today='2026-08-11')['from'] == '2026-08-10'


def test_current_day_is_not_completed_and_moscow_boundary_is_used(workspace):
    folder, db = workspace
    count = catchup.mark_success(folder, 'neftm', '2026-08-01', '2026-08-03', at='2026-08-03T20:59:59Z')
    assert count == 2 and '2026-08-03' not in saved(folder)['sources']['neftm']['days']
    count = catchup.mark_success(folder, 'neftm', '2026-08-03', '2026-08-03', at='2026-08-03T21:00:00Z')
    assert count == 1 and '2026-08-03' in saved(folder)['sources']['neftm']['days']


def test_mark_before_first_plan_does_not_hide_older_history(workspace):
    folder, db = workspace
    catchup.mark_success(folder, 'rosneft', '2026-10-01', '2026-10-30', at='2026-10-30T12:00:00+03:00')
    result = catchup.plan(folder, db, 'rosneft', today='2026-10-30')
    assert result['scope_start'] == result['from'] == '2026-08-01'


def test_open_day_barrier_survives_bootstrap_until_fresh_closed_read(workspace):
    folder, db = workspace
    catchup.mark_success(folder,'neftm','2026-08-01','2026-08-01',at='2026-08-01T23:59:59+03:00')
    (folder/'neftm-history.json').write_text(json.dumps({'rows': [], 'periods': [
        {'from':'2026-08-01','to':'2026-08-01','synced_at':'2026-08-02T00:00:01+03:00'}]}))
    result=catchup.plan(folder,db,'neftm',today='2026-08-02')
    assert result['pending_days']==1 and result['from']=='2026-08-01'
    catchup.mark_success(folder,'neftm','2026-08-01','2026-08-01',at='2026-08-02T00:05:00+03:00')
    assert catchup.plan(folder,db,'neftm',today='2026-08-02')['pending_days']==0


def test_crash_after_source_commit_before_success_mark_keeps_open_day_pending(workspace):
    folder, db = workspace
    assert catchup.begin_read(folder,'rosneft','2026-08-01','2026-08-01',at='2026-08-01T23:59:59+03:00')==1
    before=saved(folder)
    assert 'scope_start' not in before and not before['sources']['rosneft']['days']
    (folder/'rosneft-history.json').write_text(json.dumps({'rows': [], 'periods': [
        {'from':'2026-08-01','to':'2026-08-01','synced_at':'2026-08-02T00:00:01+03:00'}]}))
    # Simulate process death: no mark_success occurred after source persistence.
    assert catchup.plan(folder,db,'rosneft',today='2026-08-02')['pending_days']==1
    catchup.mark_success(folder,'rosneft','2026-08-01','2026-08-01',at='2026-08-02T00:05:00+03:00')
    assert catchup.plan(folder,db,'rosneft',today='2026-08-02')['pending_days']==0
    previous=(folder/catchup.STATE_FILE).read_bytes()
    assert catchup.begin_read(folder,'rosneft','2026-08-01','2026-08-01',at='2026-08-02T00:10:00+03:00')==0
    assert (folder/catchup.STATE_FILE).read_bytes()==previous


@pytest.mark.parametrize('first,today,expected_end,pending', [
    ('2026-12-30', '2027-01-04', '2026-12-31', 5),
    ('2028-02-28', '2028-03-03', '2028-02-29', 4),
    ('2027-02-28', '2027-03-03', '2027-02-28', 3),
])
def test_month_year_and_leap_boundaries(workspace, monkeypatch, first, today, expected_end, pending):
    folder, db = workspace
    monkeypatch.setenv('FLEET_SYNC_FROM', first)
    result = catchup.plan(folder, db, 'neftm', today=today, limit_days=31)
    assert result['from'] == first and result['to'] == expected_end and result['pending_days'] == pending


def test_scope_stays_fixed_when_known_trip_moves_back_but_explicit_fetch_extends_it(workspace):
    folder, db = workspace
    catchup.plan(folder, db, 'transtrade', today='2026-08-10')
    with sqlite3.connect(db) as connection:
        connection.execute("update records set body=? where id='trip'", (json.dumps({'date': '2009-12-01'}),))
    assert catchup.plan(folder, db, 'transtrade', today='2026-08-10')['scope_start'] == '2026-08-01'
    save_meta(db, 'transtrade_runs', [{'status': 'success', 'start': '2026-07-01', 'end': '2026-07-31',
                                    'synced_at': '2026-08-10T10:00:00+03:00'}])
    result = catchup.plan(folder, db, 'transtrade', today='2026-08-10')
    assert result['scope_start'] == '2026-07-01' and result['from'] == '2026-08-01'


def test_explicit_scope_override_can_limit_or_extend_without_erasing_marks(workspace, monkeypatch):
    folder, db = workspace
    catchup.mark_success(folder, 'transtrade', '2026-08-01', '2026-08-03', at='2026-08-10T10:00:00+03:00')
    monkeypatch.setenv('FLEET_SYNC_FROM', '2026-08-07')
    assert catchup.plan(folder, db, 'transtrade', today='2026-08-10')['from'] == '2026-08-07'
    assert '2026-08-01' in saved(folder)['sources']['transtrade']['days']
    monkeypatch.setenv('FLEET_SYNC_FROM', '2026-08-01')
    assert catchup.plan(folder, db, 'transtrade', today='2026-08-10')['from'] == '2026-08-04'


def test_tt_bootstrap_accepts_successful_reads_not_business_completeness(workspace):
    folder, db = workspace
    save_meta(db, 'transtrade_runs', [
        {'status': 'success', 'start': '2026-08-01', 'end': '2026-08-03', 'synced_at': '2026-08-03T12:00:00+03:00', 'complete': False},
        {'status': 'error', 'start': '2026-08-04', 'end': '2026-08-07', 'synced_at': '2026-08-08T12:00:00+03:00'},
    ])
    result = catchup.plan(folder, db, 'transtrade', today='2026-08-09')
    assert result['from'] == '2026-08-03' and result['pending_days'] == 6
    save_meta(db, 'transtrade_reconciliation', {'status': 'error', 'start': '2026-08-01', 'end': '2026-08-07',
              'last_success_at': '2026-08-08T12:00:00+03:00', 'attempted_at': '2026-08-09T12:00:00+03:00', 'complete': False})
    result = catchup.plan(folder, db, 'transtrade', today='2026-08-09')
    assert result['from'] == result['to'] == '2026-08-08' and result['pending_days'] == 1


@pytest.mark.parametrize('source', ['neftm', 'rosneft'])
def test_successful_empty_fuel_periods_bootstrap_but_undated_periods_do_not(workspace, source):
    folder, db = workspace
    (folder/(source+'-history.json')).write_text(json.dumps({'rows': [], 'periods': [
        {'from': '2026-07-30', 'to': '2026-08-02', 'synced_at': '2026-08-03T10:00:00+03:00'},
        {'from': '2026-08-03', 'to': '2026-08-04', 'synced_at': None},
    ]}))
    result = catchup.plan(folder, db, source, today='2026-08-06')
    assert result['scope_start'] == '2026-07-30'
    assert result['from'] == '2026-08-03' and result['pending_days'] == 3


def cell(ident, day, *, fuel=True, stamp='2026-08-10T10:00:00+03:00', status='ok'):
    row = {'vehicleId': ident, 'date': day, 'mileage': {'status': status, 'synced_at': stamp}}
    if fuel:
        row['fuel'] = {'status': 'no_signal', 'synced_at': stamp}
    return row


def test_monitoring_requires_both_metrics_for_all_current_mapped_objects(workspace, monkeypatch):
    from app import monitoring_history
    folder, db = workspace
    mapping = [{'vehicleId': 1, 'vehicle': 'CAR1'}, {'vehicleId': 2, 'vehicle': 'CAR2'}, {'vehicleId': 9, 'vehicle': None}]
    monkeypatch.setattr(monitoring_history, 'mappings', lambda *_: mapping)
    cells = {'1:2026-08-01': cell(1, '2026-08-01', status='no_data'),
             '2:2026-08-01': cell(2, '2026-08-01'),
             '1:2026-08-02': cell(1, '2026-08-02'),
             '2:2026-08-02': cell(2, '2026-08-02', fuel=False)}
    (folder/'monitoring-history.json').write_text(json.dumps({'cells': cells}))
    result = catchup.plan(folder, db, 'monitoring', today='2026-08-05', names=['CAR1', 'CAR2'], limit_days=31)
    assert result['from'] == result['to'] == '2026-08-02' and result['pending_days'] == 3
    # New mapping cannot inherit the previous pair's completion claim.
    mapping.append({'vehicleId': 3, 'vehicle': 'CAR3'})
    result = catchup.plan(folder, db, 'monitoring', today='2026-08-05', names=['CAR1', 'CAR2', 'CAR3'])
    assert result['from'] == '2026-08-01' and result['pending_days'] == 4


def test_monitoring_without_mapping_or_timestamp_never_claims_complete(workspace, monkeypatch):
    from app import monitoring_history
    folder, db = workspace
    monkeypatch.setattr(monitoring_history, 'mappings', lambda *_: [])
    catchup.mark_success(folder, 'monitoring', '2026-08-01', '2026-08-03', at='2026-08-10T10:00:00+03:00')
    assert catchup.plan(folder, db, 'monitoring', today='2026-08-05')['pending_days'] == 4
    monkeypatch.setattr(monitoring_history, 'mappings', lambda *_: [{'vehicleId': 1, 'vehicle': 'CAR1'}])
    (folder/'monitoring-history.json').write_text(json.dumps({'cells': {'x': cell(1, '2026-08-01', stamp=None)}}))
    assert catchup.plan(folder, db, 'monitoring', today='2026-08-05')['from'] == '2026-08-01'


def test_minimal_or_absent_database_is_not_created_and_defaults_to_current_month(tmp_path):
    db = tmp_path/'missing.sqlite'
    result = catchup.plan(tmp_path, db, 'transtrade', today='2026-10-03')
    assert result['scope_start'] == '2026-10-01' and result['pending_days'] == 2
    assert not db.exists()
    with sqlite3.connect(db) as connection:
        connection.execute('create table unrelated(id integer)')
    assert catchup.plan(tmp_path, db, 'transtrade', today='2026-10-03') == result


@pytest.mark.parametrize('source,start,end,stamp', [
    ('wrong', '2026-08-01', '2026-08-02', '2026-08-10T12:00:00+03:00'),
    ('neftm', True, '2026-08-02', '2026-08-10T12:00:00+03:00'),
    ('neftm', '20260801', '2026-08-02', '2026-08-10T12:00:00+03:00'),
    ('neftm', '2026-08-03', '2026-08-02', '2026-08-10T12:00:00+03:00'),
    ('neftm', '2026-08-01', '2026-08-11', '2026-08-10T12:00:00+03:00'),
    ('neftm', '2026-01-01', '2026-04-04', '2026-08-10T12:00:00+03:00'),
    ('neftm', '2026-08-01', '2026-08-02', '2026-08-10T12:00:00'),
])
def test_invalid_marks_leave_saved_state_unchanged(workspace, source, start, end, stamp):
    folder, db = workspace
    catchup.plan(folder, db, 'neftm', today='2026-08-10')
    before = (folder/catchup.STATE_FILE).read_bytes()
    with pytest.raises(ValueError):
        catchup.mark_success(folder, source, start, end, at=stamp)
    assert (folder/catchup.STATE_FILE).read_bytes() == before


def test_corrupt_state_is_not_replaced(workspace):
    folder, db = workspace
    path = folder/catchup.STATE_FILE
    path.write_text('{not valid')
    with pytest.raises(ValueError):
        catchup.plan(folder, db, 'transtrade', today='2026-08-10')
    assert path.read_text() == '{not valid'
    with pytest.raises(ValueError):
        catchup.mark_success(folder, 'transtrade', '2026-08-01', '2026-08-03', at='2026-08-10T12:00:00+03:00')
    assert path.read_text() == '{not valid'


def test_unrelated_provider_corruption_does_not_block_other_catchup(workspace):
    folder, db = workspace
    (folder/'rosneft-history.json').write_text('{broken')
    (folder/'monitoring-history.json').write_text('{broken')
    assert catchup.plan(folder, db, 'transtrade', today='2026-08-10')['pending_days'] == 9
    with pytest.raises(ValueError):
        catchup.plan(folder, db, 'rosneft', today='2026-08-10')
    with pytest.raises(ValueError):
        catchup.plan(folder, db, 'monitoring', today='2026-08-10')


def test_only_future_actual_rows_do_not_hide_current_month_gap(workspace):
    folder, db = workspace
    with sqlite3.connect(db) as connection:
        connection.execute("update records set body=? where id='trip'", (json.dumps({'date': '2099-01-01'}),))
    result = catchup.plan(folder, db, 'neftm', today='2026-08-10')
    assert result['scope_start'] == '2026-08-01' and result['pending_days'] == 9


def test_concurrent_process_marks_do_not_lose_other_sources_or_days(workspace):
    folder, db = workspace
    catchup.plan(folder, db, 'transtrade', today='2026-08-10')
    code = "from app.catchup import mark_success; import sys; mark_success(sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[3],at='2026-08-10T12:00:00+03:00')"
    children = [subprocess.Popen([sys.executable, '-c', code, str(folder), source, f'2026-08-0{day}'])
                for source in ('transtrade', 'neftm') for day in range(1, 5)]
    for process in children:
        assert process.wait(timeout=10) == 0
    state = saved(folder)
    for source in ('transtrade', 'neftm'):
        assert set(state['sources'][source]['days']) == {f'2026-08-0{day}' for day in range(1, 5)}
