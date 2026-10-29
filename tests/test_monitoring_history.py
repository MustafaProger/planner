import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from app import monitoring_history as h


def item(ident=1,**fields):
    return {'vehicleId':ident,'periods':[{'start':'2026-08-01T00:00:00','end':'2026-08-02T00:00:00',**fields}]}


def test_mapping_exact_unique_and_ambiguous(tmp_path):
    rows=[{'vehicleId':1,'name':'Газель t711pm797'},{'vehicleId':2,'name':'Atego е825ос95'},
          {'vehicleId':3,'name':'Неизвестная'},{'vehicleId':4,'name':'Дубль е825ос95'}]
    (tmp_path/'monitoring-vehicles.json').write_text(json.dumps({'rows':rows}))
    mapped=h.mappings(tmp_path,['Т711РМ797','Е825ОС95'])
    assert mapped[0]['vehicle']=='Т711РМ797'
    assert all(r['vehicle'] is None for r in mapped[1:])


def test_daily_units_zero_and_timezone():
    r=h.parse([item(mileage=12.345,mileageBegin=100,mileageEnd=112.345,motohours=7200,motohoursBegin=10000)], [1], '2026-08-01','mileage')[1]
    assert r['km']==12.345 and r['engine_hours']==2
    r=h.parse([item(mileage=0,mileageBegin=100,mileageEnd=100,motohours=0,motohoursBegin=10000)], [1], '2026-08-01','mileage')[1]
    assert r['km']==0 and r['engine_hours']==0
    r=h.parse([item(mileage=0,mileageBegin=0,mileageEnd=0,motohours=0,motohoursBegin=0)], [1], '2026-08-01','mileage')[1]
    assert r['km'] is None and r['engine_hours'] is None
    r=item(mileage=5,motohours=3600)
    r['periods'][0].update(start='2026-07-31T21:00:00Z',end='2026-08-01T21:00:00Z')
    assert h.parse([r],[1],'2026-08-01','mileage')[1]['km']==5


def test_fuel_missing_signal_is_not_zero():
    assert h.parse([item(fuelConsumption=0,fuelLevelStart=0,fuelLevelEnd=0)],[1],'2026-08-01','fuel')[1]['fuel_liters'] is None
    assert h.parse([item(fuelConsumption=0,fuelLevelStart=50,fuelLevelEnd=50)],[1],'2026-08-01','fuel')[1]['fuel_liters']==0
    assert h.parse([item(fuelConsumption=42.39)],[1],'2026-08-01','fuel')[1]['fuel_liters']==42.39
    assert h.parse([],[1],'2026-08-01','fuel')[1]['status']=='no_data'
    assert h.numeric(float('nan')) is None and h.numeric(-1) is None


def test_wrong_period_or_duplicate_fails():
    with pytest.raises(ValueError):h.parse([item(),item()],[1],'2026-08-01','fuel')
    with pytest.raises(ValueError):h.parse([item(2)],[1],'2026-08-01','fuel')
    with pytest.raises(ValueError):h.parse([item()],[1],'2026-08-02','fuel')
    with pytest.raises(ValueError):h.period('2026-08-02','2026-08-01')
    with pytest.raises(ValueError):h.period(dt.datetime.now(h.MSK).date().isoformat(),dt.datetime.now(h.MSK).date().isoformat())


def test_overlay_replaces_each_metric_and_keeps_excel_interval():
    excel=[{'vehicle':'X','date':'2026-08-01','km':100,'hours':9,'engine_hours':7}]
    api=[{'vehicle':'X','date':'2026-08-01','km':110,'engine_hours':8,'fuel_liters':15,'mileage_status':'ok','fuel_status':'ok','synced_at':'now'}]
    rows=h.merge_satellite(excel,api)
    assert len(rows)==1 and rows[0]['km']==110 and rows[0]['hours']==9 and rows[0]['engine_hours']==8
    assert rows[0]['sources']['hours']=='Excel'
    assert rows[0]['sources']['km']=='ГЛОНАССсофт API'
    api[0]['km']=None
    assert h.merge_satellite(excel,api)[0]['km']==100
    assert excel[0]['km']==100


def test_resumable_batches_and_failed_chunk_preservation(tmp_path,monkeypatch):
    calls=[]
    def read(self,method,body):
        calls.append((method,body))
        if method.endswith('fuelConsumption'):raise ValueError('transient')
        return [item(i,mileage=i,motohours=3600) for i in body['vehicleIds']]
    monkeypatch.setattr(h.Client,'read',read)
    matched=[{'vehicleId':i,'vehicle':str(i)} for i in range(1,5)]
    job={'status':'running','done':0,'failed':0,'refresh':False}
    h.JOB_LOCK.acquire();h.run(tmp_path,matched,['2026-08-01'],job)
    assert job['status']=='partial' and job['done']==4 and job['failed']==4
    assert all(len(body['vehicleIds'])<=3 for _,body in calls)
    saved=(tmp_path/'monitoring-history.json').read_text()
    calls.clear();job.update(status='running',done=0,failed=0)
    h.JOB_LOCK.acquire();h.run(tmp_path,matched,['2026-08-01'],job)
    assert all(method.endswith('fuelConsumption') for method,_ in calls)
    assert (tmp_path/'monitoring-history.json').read_text()==saved
    assert not h.JOB_LOCK.locked()


def test_analytics_weighted_fuel_missing_days_and_engine_separate():
    from app.analytics import report,reconcile
    trips=[{'id':str(i),'date':f'2026-08-0{i}','vehicle':'X','category':'Рейс','hours':9,'km':100,'revenue':1000,'payout':100} for i in (1,2,3)]
    api=[{'vehicle':'X','date':'2026-08-01','km':100,'engine_hours':2,'fuel_liters':10,'mileage_status':'ok','fuel_status':'ok','synced_at':'now'},
         {'vehicle':'X','date':'2026-08-02','km':300,'engine_hours':3,'fuel_liters':60,'mileage_status':'ok','fuel_status':'ok','synced_at':'now'},
         {'vehicle':'X','date':'2026-08-03','km':None,'engine_hours':None,'fuel_liters':None,'mileage_status':'no_data','fuel_status':'no_signal','synced_at':'now'}]
    d={'trips':trips,'plans':[],'satellite':h.merge_satellite([],api)}
    row=report(d,{'from':'2026-08-01','to':'2026-08-03'})['rows'][0]
    assert row['fuel_liters']==70 and row['fuel_l_per_100_km']==17.5
    assert row['fuel_days']==2 and row['period_days']==3
    assert row['sat_engine_hours']==5 and row['sat_hours'] is None
    assert row['delta_km'] is None and row['missing_trip_days']==1
    rows=reconcile(d,{})
    assert rows[0]['sat_engine_hours']==2 and rows[0]['delta_hours'] is None
    assert rows[2]['state']=='Нет спутника' and rows[2]['fuel_liters'] is None
    assert rows[0]['km_source']=='ГЛОНАССсофт API'
    assert 'fuel_liters' not in report(d,{'group':'driver'})['rows'][0]


def test_refresh_empty_does_not_erase_valid_data(tmp_path,monkeypatch):
    cell={'vehicleId':1,'date':'2026-08-01','mileage':{'status':'ok','km':50,'engine_hours':1,'synced_at':'old'},'fuel':{'status':'ok','fuel_liters':5,'synced_at':'old'}}
    (tmp_path/'monitoring-history.json').write_text(json.dumps({'cells':{h.key(1,'2026-08-01'):cell}}))
    monkeypatch.setattr(h.Client,'read',lambda *args:[])
    job={'status':'running','done':0,'failed':0,'refresh':True}
    h.JOB_LOCK.acquire();h.run(tmp_path,[{'vehicleId':1,'vehicle':'X'}],['2026-08-01'],job)
    assert h.load(tmp_path)['cells'][h.key(1,'2026-08-01')]==cell
    assert job['done']==2


def test_cross_process_lock_detected(tmp_path):
    import fcntl
    (tmp_path/'monitoring-history-job.json').write_text(json.dumps({'status':'running'}))
    with open(tmp_path/'monitoring-history.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert h.job_status(tmp_path)['status']=='running'
    assert h.job_status(tmp_path)['status']=='interrupted'


def test_authorization_failure_stops_without_batch_retry(tmp_path,monkeypatch):
    calls=[]
    def deny(*args):calls.append(1);raise h.AuthenticationError('denied')
    monkeypatch.setattr(h.Client,'read',deny)
    job={'status':'running','done':0,'failed':0,'refresh':False}
    h.JOB_LOCK.acquire();h.run(tmp_path,[{'vehicleId':i,'vehicle':str(i)} for i in range(3)],['2026-08-01'],job)
    assert len(calls)==1 and job['status']=='partial'


def test_refresh_partial_metric_keeps_known_engine_hours(tmp_path,monkeypatch):
    cell={'vehicleId':1,'date':'2026-08-01','mileage':{'status':'ok','km':50,'engine_hours':1,'synced_at':'old'}}
    (tmp_path/'monitoring-history.json').write_text(json.dumps({'cells':{h.key(1,'2026-08-01'):cell}}))
    monkeypatch.setattr(h.Client,'read',lambda self,method,body:[item(mileage=55,motohours=0)] if method.endswith('mileageAndMotohours') else [])
    job={'status':'running','done':0,'failed':0,'refresh':True}
    h.JOB_LOCK.acquire();h.run(tmp_path,[{'vehicleId':1,'vehicle':'X'}],['2026-08-01'],job)
    saved=h.load(tmp_path)['cells'][h.key(1,'2026-08-01')]['mileage']
    assert saved['km']==55 and saved['engine_hours']==1 and saved['retained_at']=='old'


def test_rate_limit_stops_without_splitting_batch(tmp_path,monkeypatch):
    calls=[]
    def limited(*args):calls.append(1);raise h.RateLimitError('Ограничена частота')
    monkeypatch.setattr(h.Client,'read',limited)
    job={'status':'running','done':0,'failed':0,'refresh':False}
    h.JOB_LOCK.acquire();h.run(tmp_path,[{'vehicleId':i,'vehicle':str(i)} for i in range(3)],['2026-08-01'],job)
    assert len(calls)==1 and job['status']=='partial'
    assert 'Ограничена частота' in job['message']


def test_reported_zero_with_mileage_is_flagged_and_excluded(tmp_path):
    (tmp_path/'monitoring-vehicles.json').write_text(json.dumps({'rows':[{'vehicleId':1,'name':'Т711РМ797'}]}))
    cells={h.key(1,'2026-08-01'):{'vehicleId':1,'date':'2026-08-01','mileage':{'km':150,'engine_hours':6,'status':'ok'},'fuel':{'fuel_liters':0,'status':'ok'}}}
    (tmp_path/'monitoring-history.json').write_text(json.dumps({'cells':cells}))
    r=h.daily_rows(tmp_path,['Т711РМ797'])[0]
    assert r['fuel_liters'] is None and r['fuel_status']=='suspect_zero'
    assert h.load(tmp_path)['cells'][h.key(1,'2026-08-01')]['fuel']['fuel_liters']==0
    cells[h.key(1,'2026-08-01')]['mileage']['km']=0
    (tmp_path/'monitoring-history.json').write_text(json.dumps({'cells':cells}))
    assert h.daily_rows(tmp_path,['Т711РМ797'])[0]['fuel_liters']==0
    zero=h.daily_rows(tmp_path,['Т711РМ797'])[0]
    zero['km']=None
    merged=h.merge_satellite([{'vehicle':'Т711РМ797','date':'2026-08-01','km':100}], [zero])[0]
    assert merged['fuel_liters'] is None and merged['fuel_status']=='suspect_zero'
