import datetime as dt
import json
import threading
import time

import pytest

from app import autosync, refresh, alerts
from app.neftm import write_json


def until(check, seconds=4):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=check()
        if result:return result
        time.sleep(.01)
    raise AssertionError('Background condition did not complete')


@pytest.fixture
def engine(tmp_path,monkeypatch):
    service=refresh.RefreshService(tmp_path,tmp_path/'fleet.sqlite',lambda:{'vehicles':[]})
    scheduler=autosync.Scheduler(service,300)
    service.engine=scheduler
    monkeypatch.setattr(scheduler,'_configured',lambda source:source in ('transtrade','rosneft'))
    monkeypatch.setattr(scheduler,'_current',lambda source:{'message':'ok'})
    monkeypatch.setattr(scheduler,'_history',lambda source:{'message':'history ok','pending_days':0})
    monkeypatch.setattr(alerts,'observe',lambda *a,**kw:None)
    yield scheduler
    scheduler.stop(join_timeout=2)


def test_sources_do_not_wait_for_slow_provider(engine,monkeypatch):
    gate=threading.Event();blocked=threading.Event()
    def current(source):
        if source=='transtrade':
            blocked.set();gate.wait(3)
        return {'message':'ok'}
    monkeypatch.setattr(engine,'_current',current)
    engine.start()
    try:
        assert blocked.wait(1)
        until(lambda:(autosync.read_state(engine.folder)['tasks']['rosneft:current'].get('status')=='success'))
        assert engine.health()['healthy']
        assert autosync.read_state(engine.folder)['tasks']['transtrade:current']['status']=='running'
    finally:gate.set()


def test_restart_replays_interrupted_jobs_and_keeps_success_due(engine,monkeypatch):
    future=(autosync.now()+dt.timedelta(hours=1)).isoformat()
    write_json(engine.folder/autosync.STATE,dict(version=1,tasks={
        'transtrade:current':{'status':'running','next_run_at':future},
        'rosneft:current':{'status':'success','next_run_at':future,'last_success_at':autosync.now().isoformat()},
        'transtrade:history':{'status':'success','next_run_at':future},
        'rosneft:history':{'status':'success','next_run_at':future}}))
    calls=[]
    monkeypatch.setattr(engine,'_current',lambda source:calls.append(source) or {'message':'ok'})
    engine.start()
    until(lambda:calls)
    assert calls==['transtrade']
    until(lambda:autosync.read_state(engine.folder)['tasks']['transtrade:current']['status']=='success')


@pytest.mark.parametrize('damaged',['{broken',json.dumps({'version':1,'tasks':{'transtrade:current':{'next_run_at':None}}}),json.dumps({'version':1,'tasks':{'transtrade:orphan:current':{}}})])
def test_corrupt_schedule_rebuilt_without_resetting_coverage(engine,damaged):
    (engine.folder/autosync.STATE).write_text(damaged)
    ledger=engine.folder/'refresh-coverage.json';ledger.write_text('protected ledger')
    engine.start()
    until(lambda:engine.health()['healthy'])
    assert list(engine.folder.glob('refresh-auto.json.corrupt-*'))
    assert ledger.read_text()=='protected ledger'


def test_transient_scheduler_write_failure_recovers(engine,monkeypatch):
    original=engine._beat;calls=[]
    def beat():
        calls.append(1)
        if len(calls)==1:raise OSError('synthetic disk failure')
        original()
    monkeypatch.setattr(engine,'_beat',beat)
    engine.start()
    until(lambda:engine.health()['healthy'])
    assert len(calls)>=2


def test_provider_error_preserves_prior_success_and_other_provider_runs(engine,monkeypatch):
    original=autosync.now()-dt.timedelta(minutes=10)
    write_json(engine.folder/autosync.STATE,dict(version=1,tasks={
        'transtrade:current':{'status':'success','next_run_at':original.isoformat(),'last_success_at':original.isoformat()}}))
    def current(source):
        if source=='transtrade':raise ValueError('Unavailable')
        return {'message':'ok'}
    monkeypatch.setattr(engine,'_current',current)
    engine.start()
    until(lambda:autosync.read_state(engine.folder)['tasks'].get('rosneft:current',{}).get('status')=='success')
    task=autosync.read_state(engine.folder)['tasks']['transtrade:current']
    assert task['status']=='error' and task['last_success_at']==original.isoformat()
    assert task['error_since'] and engine.health()['healthy']


def test_upgrade_keeps_known_freshness_for_failed_source(engine,monkeypatch):
    prior=(autosync.now()-dt.timedelta(days=1)).isoformat()
    write_json(engine.folder/'refresh-state.json',dict(sources={'transtrade':{'last_success_at':prior}}))
    monkeypatch.setattr(engine,'_current',lambda source:(_ for _ in ()).throw(ValueError('Unavailable')))
    engine.start()
    until(lambda:(autosync.read_state(engine.folder) or {}).get('tasks',{}).get('transtrade:current',{}).get('status')=='error')
    state=engine.service.status()
    assert state['sources']['transtrade']['last_success_at']==prior
    assert any(x['key']=='source:transtrade' for x in state['alerts']['incidents'])


@pytest.mark.parametrize('missing',[False,True])
def test_bad_provider_configuration_does_not_block_others(engine,monkeypatch,missing):
    monkeypatch.setenv('FLEET_REQUIRED_PROVIDERS','transtrade')
    def configured(source):
        if source=='transtrade':
            if missing:return False
            raise AttributeError('synthetic malformed config')
        return source=='rosneft'
    monkeypatch.setattr(engine,'_configured',configured)
    engine.start()
    until(lambda:(autosync.read_state(engine.folder) or {}).get('tasks',{}).get('rosneft:current',{}).get('status')=='success')
    task=autosync.read_state(engine.folder)['tasks']['transtrade:current']
    assert task['status']=='error' and task['error_since']
    assert engine.health()['healthy']


def test_deadline_failure_is_liveness_failure_not_silent_hang(engine):
    engine.start()
    until(lambda:engine.health()['healthy'])
    with engine.guard:
        engine.jobs['hung']={'deadline_at':(autosync.now()-dt.timedelta(seconds=1)).isoformat()}
    assert not engine.health()['healthy']
    engine.jobs.pop('hung')


def test_external_web_reports_stale_worker_even_if_schedule_success(engine):
    old=(autosync.now()-dt.timedelta(minutes=5)).isoformat()
    write_json(engine.folder/autosync.STATE,dict(version=1,tasks={'transtrade:current':{'status':'success','next_run_at':old,'last_success_at':old}},started_at=old))
    write_json(engine.folder/autosync.HEARTBEAT,dict(at=old,pid=123,status='running',jobs={}))
    state=engine.service.status()
    assert not state['server_scheduler']
    assert any(x['key']=='worker' for x in state['alerts']['incidents'])


def test_two_schedulers_have_only_one_leader(engine,monkeypatch):
    calls=[]
    monkeypatch.setattr(engine,'_current',lambda source:calls.append(source) or {'message':'ok'})
    engine.start();until(lambda:engine.health()['healthy'])
    other=autosync.Scheduler(engine.service,300)
    monkeypatch.setattr(other,'_current',lambda source:pytest.fail('Second leader executed source'))
    other.start();other.thread.join(1)
    assert not other.health()['healthy'] and not other.thread.is_alive()
    assert len(calls)==len(set(calls))


def test_stop_is_bounded_and_marks_heartbeat_stopped(engine,monkeypatch):
    gate=threading.Event()
    monkeypatch.setattr(engine,'_current',lambda source:gate.wait(3) or {'message':'ok'})
    engine.start();until(lambda:engine.jobs)
    start=time.monotonic();engine.stop(join_timeout=.05)
    assert time.monotonic()-start<.5
    assert json.loads((engine.folder/autosync.HEARTBEAT).read_text())['status']=='stopping'
    gate.set()
