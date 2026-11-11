import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import autosync, catchup, fuel_history, monitoring_history, neftm


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv('FLEET_SYNC_FROM', raising=False)
    fixed = dt.datetime(2026, 9, 1, 10, 0, tzinfo=autosync.MSK)
    monkeypatch.setattr(autosync, 'now', lambda: fixed)
    db = tmp_path/'fleet.sqlite'
    with sqlite3.connect(db) as connection:
        connection.execute('create table records(kind text,body text)')
        connection.execute('insert into records values(?,?)', ('trips', json.dumps({'date':'2026-08-31'})))
    service = SimpleNamespace(data_dir=tmp_path, db_path=db, get_dataset=lambda: {'vehicles':['CAR1','CAR2']})
    scheduler = autosync.Scheduler(service, 300)
    scheduler._load()
    for source in autosync.NAMES:
        scheduler.state['tasks'][source+':history'].update(
            recent_checked_at=fixed.isoformat(), recent_day='2026-08-31')
    scheduler._save()
    return scheduler


def test_provider_commit_before_failed_checkpoint_is_recovered_without_reappending(engine, monkeypatch):
    calls = []
    def sync(folder, start, end):
        calls.append((start,end))
        result = {'provider':'neftm', 'from':start, 'to':end, 'synced_at':autosync.now().isoformat(),
                  'rows':[{'dateRec':start+'T08:00:00', 'amount':'5'}]}
        fuel_history.persist(folder,result)
        return result
    monkeypatch.setattr(neftm,'sync',sync)
    mark = catchup.mark_success
    def fail(*args, **kwargs):
        raise OSError('synthetic checkpoint failure')
    monkeypatch.setattr(catchup,'mark_success',fail)
    with pytest.raises(OSError):
        engine._history('neftm')
    assert len(fuel_history.read(engine.folder,'neftm')['rows']) == 1
    monkeypatch.setattr(catchup,'mark_success',mark)
    restarted = autosync.Scheduler(engine.service,300)
    restarted._load()
    result = restarted._history('neftm')
    assert result['pending_days'] == 0
    assert calls == [('2026-08-31','2026-08-31')]
    assert len(fuel_history.read(engine.folder,'neftm')['rows']) == 1


def test_new_month_current_refresh_does_not_hide_missed_previous_month(engine,monkeypatch):
    calls=[]
    def sync(folder,start,end):
        calls.append((start,end))
        return {'provider':'neftm','rows':[]}
    monkeypatch.setattr(neftm,'sync',sync)
    engine._current('neftm')
    state=catchup.plan(engine.folder,engine.service.db_path,'neftm',today=autosync.now().date())
    assert state['from'] == state['to'] == '2026-08-31'
    restarted=autosync.Scheduler(engine.service,300)
    restarted._load()
    result=restarted._history('neftm')
    assert result['pending_days'] == 0
    assert calls == [('2026-09-01','2026-09-01'),('2026-08-31','2026-08-31')]


def test_current_request_crossing_midnight_does_not_certify_partial_day(engine,monkeypatch):
    clock=[dt.datetime(2026,9,1,23,59,59,tzinfo=autosync.MSK)]
    monkeypatch.setattr(autosync,'now',lambda:clock[0])
    def sync(folder,start,end):
        clock[0]=dt.datetime(2026,9,2,0,0,1,tzinfo=autosync.MSK)
        result={'provider':'neftm','from':start,'to':end,'synced_at':clock[0].isoformat(),'rows':[]}
        fuel_history.persist(folder,result)
        return result
    monkeypatch.setattr(neftm,'sync',sync)
    engine._current('neftm')
    ledger=json.loads((engine.folder/catchup.STATE_FILE).read_text())
    assert '2026-09-01' not in ledger['sources']['neftm']['days']
    catchup.plan(engine.folder,engine.service.db_path,'neftm',today=clock[0].date())
    ledger=json.loads((engine.folder/catchup.STATE_FILE).read_text())
    assert '2026-09-01' not in ledger['sources']['neftm']['days']


def test_recent_fuel_recheck_crosses_month_and_replaces_late_data_once(engine,monkeypatch):
    with sqlite3.connect(engine.service.db_path) as connection:
        connection.execute('update records set body=?',(json.dumps({'date':'2026-08-24'}),))
    catchup.mark_success(engine.folder,'neftm','2026-08-24','2026-08-31',at=autosync.now())
    fuel_history.persist(engine.folder,{'provider':'neftm','from':'2026-08-24','to':'2026-08-31',
        'synced_at':autosync.now().isoformat(), 'rows':[
            {'dateRec':'2026-08-24T08:00:00','costClient':'11'},
            {'dateRec':'2026-08-31T08:00:00','costClient':'10'}]})
    engine.state['tasks']['neftm:history']['recent_day']='2026-08-30'
    calls=[]
    def sync(folder,start,end):
        calls.append((start,end))
        result={'provider':'neftm','from':start,'to':end,'synced_at':autosync.now().isoformat(),
                'rows':[{'dateRec':'2026-08-31T08:00:00','costClient':'20'}]}
        fuel_history.persist(folder,result)
        return result
    monkeypatch.setattr(neftm,'sync',sync)
    result=engine._history('neftm')
    assert calls==[('2026-08-25','2026-08-31')]
    assert result['pending_days']==0 and result['recent_day']=='2026-08-31'
    rows=fuel_history.read(engine.folder,'neftm')['rows']
    assert [(r['dateRec'][:10],r['costClient']) for r in rows]==[('2026-08-24','11'),('2026-08-31','20')]


def test_partial_monitoring_resumes_missing_day_with_saved_cells(engine,monkeypatch):
    monkeypatch.setattr(monitoring_history,'mappings',lambda *_:[
        {'vehicleId':1,'vehicle':'CAR1'},{'vehicleId':2,'vehicle':'CAR2'}])
    metrics={'mileage':{'status':'ok','synced_at':autosync.now().isoformat(),'km':5},
             'fuel':{'status':'no_signal','synced_at':autosync.now().isoformat()}}
    first={'vehicleId':1,'date':'2026-08-31',**metrics}
    path=engine.folder/'monitoring-history.json'
    path.write_text(json.dumps({'cells':{'1:2026-08-31':first}}))
    status={'value':None};calls=[]
    monkeypatch.setattr(monitoring_history,'job_status',lambda _:status['value'])
    def start(folder,names,begin,end,refresh=False):
        calls.append((begin,end,refresh))
        status['value']={'id':str(len(calls)),'status':'partial' if len(calls)==1 else 'complete'}
        if len(calls)==2:
            history=json.loads(path.read_text())
            history['cells']['2:2026-08-31']={'vehicleId':2,'date':'2026-08-31',**metrics}
            path.write_text(json.dumps(history))
        return status['value']
    monkeypatch.setattr(monitoring_history,'start',start)
    with pytest.raises(ValueError,match='Часть истории'):
        engine._history('monitoring')
    before=json.loads(path.read_text())['cells']['1:2026-08-31']
    restarted=autosync.Scheduler(engine.service,300)
    restarted._load()
    waiting=restarted._history('monitoring')
    assert waiting['pending_days']==1 and waiting['from'] is None
    assert len(calls)==1
    fixed=autosync.now()
    monkeypatch.setattr(autosync,'now',lambda:fixed+dt.timedelta(hours=1))
    result=restarted._history('monitoring')
    assert result['pending_days']==0
    assert calls==[('2026-08-31','2026-08-31',False),('2026-08-31','2026-08-31',False)]
    assert json.loads(path.read_text())['cells']['1:2026-08-31']==before


def test_monitoring_recent_gaps_take_priority_and_archive_errors_rotate(engine,monkeypatch):
    monkeypatch.setenv('FLEET_SYNC_FROM','2025-01-01')
    monkeypatch.setattr(monitoring_history,'mappings',lambda *_:[{'vehicleId':1,'vehicle':'CAR1'}])
    recent_start='2026-08-02'
    catchup.plan(engine.folder,engine.service.db_path,'monitoring',today=autosync.now().date(),names=['CAR1'])
    catchup.mark_success(engine.folder,'monitoring','2026-08-03','2026-08-31',at=autosync.now())
    attempts=[]
    def pull(names,first,last,*,refresh):
        assert first==last and not refresh
        attempts.append(first)
        if first=='2025-01-01':
            raise autosync.IncompleteMonitoringDay('Часть истории')
    monkeypatch.setattr(engine,'_monitoring_day',pull)
    assert engine._history('monitoring')['from']=='2025-01-01'
    with pytest.raises(autosync.IncompleteMonitoringDay):
        engine._history('monitoring')
    assert engine._history('monitoring')['from']=='2025-01-03'
    assert attempts==[recent_start,'2025-01-01','2025-01-02']
    ledger=json.loads((engine.folder/catchup.STATE_FILE).read_text())
    assert '2025-01-01' not in ledger['sources']['monitoring']['days']
    assert '2025-01-02' in ledger['sources']['monitoring']['days']


def test_slow_source_history_does_not_block_another_sources_current_refresh(engine,monkeypatch):
    engine._load()
    monkeypatch.setattr(engine,'_configured',lambda _:True)
    gate,entered,completed=threading.Event(),threading.Event(),threading.Event()
    def history(source):
        entered.set()
        gate.wait(2)
        return {'message':'history complete','pending_days':0}
    def current(source):
        assert source=='transtrade'
        completed.set()
        return {'message':'fresh'}
    monkeypatch.setattr(engine,'_history',history)
    monkeypatch.setattr(engine,'_current',current)
    engine._launch('monitoring','history')
    assert entered.wait(1)
    try:
        engine._launch('transtrade','current')
        assert completed.wait(1)
        engine.threads['transtrade:current'].join(1)
        assert engine.state['tasks']['transtrade:current']['status']=='success'
        assert 'monitoring:history' in engine.jobs
        engine._launch('monitoring','current')
        assert 'monitoring:current' not in engine.jobs
    finally:
        gate.set()
        engine.stop(join_timeout=2)
