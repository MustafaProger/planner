import os,tempfile,json,datetime as dt
from pathlib import Path
import pytest
os.environ['FLEET_DATA']=tempfile.mkdtemp(prefix='fleet-tests-')
from app import server
from app.importer import load_excel,hours,vehicle
from excel_fixture import books
from app.analytics import report,reconcile
@pytest.fixture(scope='module')
def source_books(tmp_path_factory):return books(tmp_path_factory.mktemp('portable-excel'))
@pytest.fixture(scope='module')
def data(source_books):return load_excel(*source_books)
@pytest.fixture()
def client(monkeypatch,source_books):
    monkeypatch.setattr(server,'load_excel',lambda *paths:load_excel(*(paths or source_books)))
    server.init();c=server.app.test_client()
    with c.session_transaction() as s:s['uid']=1;s['csrf']='test'
    return c
H={'X-CSRF-Token':'test'}
def test_transtrade_reconcile_authorization_and_outcomes(client,monkeypatch):
    from app import transtrade
    path='/api/transtrade/reconcile'
    assert server.app.test_client().post(path,json={}).status_code==401
    assert client.post(path,json={}).status_code==403
    assert client.post(path,json=[],headers=H).status_code==400
    calls=[]
    def reconcile(*args,**kwargs):
        calls.append(kwargs);return {'status':'success','processed':2,'discovered_by_id':1}
    monkeypatch.setattr(transtrade,'reconcile',reconcile)
    assert client.post(path,json={},headers=H).status_code==200
    assert calls==[{'force':True}]
    for status,field,code in [('error','error',400),('busy','reason',409)]:
        monkeypatch.setattr(transtrade,'reconcile',lambda *a,**k:dict(status=status,**{field:'test'}))
        assert client.post(path,json={},headers=H).status_code==code
    monkeypatch.setattr(server,'user',lambda:{'id':99,'role':'viewer','vehicles':[]})
    assert client.post(path,json={},headers=H).status_code==403

def test_rosneft_role_csrf_and_sync(client,monkeypatch):
    from app import rosneft
    assert server.app.test_client().get('/api/rosneft').status_code==401
    assert client.get('/api/rosneft').status_code==200
    assert client.post('/api/rosneft/sync',json={}).status_code==403
    assert client.post('/api/rosneft/sync',json=[],headers=H).status_code==400
    calls=[]
    def fake_sync(data_dir,start,end):
        calls.append((start,end));return {'from':start,'to':end,'rows':[],'cards':[]}
    monkeypatch.setattr(rosneft,'sync',fake_sync)
    assert client.post('/api/rosneft/sync',json={'from':'2026-08-01','to':'2026-08-31'},headers=H).status_code==200
    assert calls==[('2026-08-01','2026-08-31')]
    monkeypatch.setattr(server,'user',lambda:{'id':99,'role':'logist','vehicles':[]})
    assert client.get('/api/rosneft').status_code==403
    assert client.post('/api/rosneft/sync',json={},headers=H).status_code==403

def test_reconcile_missing_not_zero(data):
    data=dict(data,trips=[*data['trips'],dict(data['trips'][0],id='missing-day',date='2026-08-03')])
    rows=reconcile(data,{})
    assert any(r['sat_km'] is None and r['delta_km'] is None for r in rows)
    for r in rows:
        if r['state']=='Сопоставлено':assert r['delta_km']==pytest.approx(r['tt_km']-r['sat_km'])
def test_duration_and_normalization():
    assert hours(dt.timedelta(days=2,hours=5))==53
    assert vehicle('T711PM797')=='Т711РМ797'
def test_auth_and_csrf(client):
    assert server.app.test_client().get('/api/data').status_code==401
    assert client.post('/api/import',json={}).status_code==403
    assert client.get('/api/users').status_code==200
    assert client.get('/data/local-login.txt').status_code==404
    assert client.get('/api/data',headers={'Host':'evil.example'}).status_code==400

def test_manual_idempotence_and_soft_delete(client,data):
    b=dict(date='2026-12-01',end_date='2026-12-02',kind='vehicle',entity='Т711РМ797',reason='Сервис')
    assert client.post('/api/manual/statuses',json=b,headers=H).json['created']==2
    assert client.post('/api/manual/statuses',json=b,headers=H).json['created']==0
    rows=client.get('/api/data').json['statuses'];r=next(r for r in rows if r['date']=='2026-12-01')
    assert client.delete('/api/manual/'+r['id'],json={'revision':r['revision'],'delete_token':r.get('delete_token')},headers=H).status_code==200
    assert not any(x.get('id')==r['id'] for x in client.get('/api/data').json['statuses'])
def test_role_boundaries_and_assignment(client):
    r=client.post('/api/users',headers=H,json=dict(name='TestLogist',password='a-test-only-password',role='logist',vehicles=['Т711РМ797']));assert r.status_code==200
    log=server.app.test_client();assert log.post('/api/login',json={'name':'TestLogist','password':'a-test-only-password'}).status_code==200
    token=log.get('/api/session').json['csrf'];h={'X-CSRF-Token':token}
    assert log.post('/api/import',headers=h,json={}).status_code==403
    assert log.get('/api/users').status_code==403
    b=dict(date='2026-12-03',kind='vehicle',entity='У930ЕХ797',reason='Сервис')
    assert log.post('/api/manual/statuses',headers=h,json=b).status_code==403
    b['entity']='Т711РМ797';assert log.post('/api/manual/statuses',headers=h,json=b).status_code==200

def test_plan_weekdays_and_rate(client,data):
    b=dict(date='2026-12-07',end_date='2026-12-13',vehicle='Т711РМ797',driver='Фаллахи Динислам Сергеевич',route=data['routes'][0]['id'],weekdays=[0,2,4])
    r=client.post('/api/manual/plans',headers=H,json=b);assert r.status_code==200 and r.json['created']==3
    assert client.post('/api/manual/plans',headers=H,json=b).json['created']==0
    plans=[p for p in client.get('/api/data').json['plans'] if p['date'].startswith('2026-12')]
    assert len(plans)==3 and all(p['revenue']==data['routes'][0]['revenue'] for p in plans)

def test_reimport_preserves_manual(client):
    before=client.get('/api/data').json
    assert client.post('/api/import',headers=H,json={}).status_code==200
    after=client.get('/api/data').json
    assert len(after['plans'])==len(before['plans']) and len(after['trips'])==len(before['trips'])
    assert client.post('/api/import',headers=H,json={}).status_code==200
    assert len(client.get('/api/data').json['trips'])==len(before['trips'])


def test_page_navigation_and_unknown_paths(client):
    assert client.get('/integrations/axenta').location=='/integrations/monitoring'
    for path in ['/analytics/statistics','/analytics/dashboard','/analytics/comparison','/analytics/reconcile','/planning/calendar','/planning/planner','/data/orders','/data/directories','/data/connections','/data/users','/integrations/neftm','/integrations/monitoring','/integrations/rosneft','/integrations/transtrade']:
        response=client.get(path)
        assert response.status_code==200
        assert b'/static/main.js' in response.data
    for path in ['/data/local-login.txt','/analytics/unknown','/planning/users','/api/unknown']:
        assert client.get(path).status_code==404
    # Serving the shell at a deep link does not grant access to its protected data.
    anonymous=server.app.test_client()
    assert anonymous.get('/data/users').status_code==200
    assert anonymous.get('/api/users').status_code==401


def test_neftm_endpoints_permissions_and_csrf(client, monkeypatch, tmp_path):
    from app import neftm
    monkeypatch.setattr(server,'DATA',tmp_path)
    assert client.get('/api/neftm').json=={'configured':False,'snapshot':None}
    assert client.post('/api/neftm/sync',json={}).status_code==403
    assert client.post('/api/neftm/sync',json={},headers=H).status_code==400
    captured=[]
    def sync(data_dir,start,end):
        captured.append((start,end))
        return {'from':start,'to':end,'rows':[],'synced_at':'2026-10-27T10:00:00+00:00'}
    monkeypatch.setattr(neftm,'sync',sync)
    assert client.post('/api/neftm/sync',json={'from':'2026-08-01','to':'2026-08-31'},headers=H).status_code==200
    assert captured==[('2026-08-01','2026-08-31')]
    with server.db() as c:
        uid=c.execute("insert into users(name,password,role,vehicles) values(?,?,?,?)",('neftm-test-viewer','unused','viewer','[]')).lastrowid
    with client.session_transaction() as s:s['uid']=uid
    assert client.get('/api/neftm').status_code==403
    assert client.post('/api/neftm/sync',json={},headers=H).status_code==403
    with client.session_transaction() as s:s.clear()
    assert client.get('/api/neftm').status_code==401


def test_monitoring_permissions_and_csrf(client,monkeypatch):
    from app import monitoring
    called=[]
    monkeypatch.setattr(monitoring,'sync',lambda _:called.append(True) or {'rows':[]})
    assert server.app.test_client().get('/api/monitoring').status_code==401
    assert client.post('/api/monitoring/sync',json={}).status_code==403
    assert client.post('/api/monitoring/sync',json={},headers=H).status_code==200
    assert len(called)==1
    with server.db() as c:
        c.execute("insert into users(name,password,role,vehicles) values(?,?,?,?)",('MonitoringViewer','unused','viewer','[]'))
        uid=c.execute("select id from users where name='MonitoringViewer'").fetchone()['id']
    viewer=server.app.test_client()
    with viewer.session_transaction() as s:s['uid']=uid;s['csrf']='test'
    assert viewer.get('/api/monitoring').status_code==403
    assert viewer.post('/api/monitoring/sync',json={},headers=H).status_code==403
    assert len(called)==1


def test_monitoring_history_auth_csrf_start(client,monkeypatch):
    from app import monitoring_history as mh
    calls=[]
    monkeypatch.setattr(mh,'start',lambda *args:calls.append(args) or {'from':'2026-08-01','to':'2026-08-02'})
    anon=server.app.test_client()
    assert anon.get('/api/monitoring/history').status_code==401
    assert client.post('/api/monitoring/history/sync',json={}).status_code==403
    assert client.post('/api/monitoring/history/sync',json={'from':'2026-08-01','to':'2026-08-02','refresh':'true'},headers=H).status_code==400
    assert client.post('/api/monitoring/history/sync',json={'from':'2026-08-01','to':'2026-08-02'},headers=H).status_code==202
    assert len(calls)==1
    with server.db() as c:
        c.execute("insert into users(name,password,role,vehicles) values(?,?,?,?)",('HistoryViewer','unused','viewer','[]'))
        uid=c.execute("select id from users where name='HistoryViewer'").fetchone()['id']
    viewer=server.app.test_client()
    with viewer.session_transaction() as s:s['uid']=uid;s['csrf']='test'
    assert viewer.get('/api/monitoring/history').status_code==403
    assert viewer.post('/api/monitoring/history/sync',json={},headers=H).status_code==403
    assert len(calls)==1

def test_transtrade_authorization_csrf_and_readonly_sync(client,monkeypatch):
    from app import transtrade
    assert server.app.test_client().get('/api/transtrade').status_code==401
    assert client.get('/api/transtrade').status_code==200
    assert client.post('/api/transtrade/sync',json={}).status_code==403
    assert client.post('/api/transtrade/sync',json=[],headers=H).status_code==400
    calls=[]
    def fake_sync(data_dir,db_path,start,end):
        calls.append((start,end));return dict(start=start,end=end,received=0)
    monkeypatch.setattr(transtrade,'sync',fake_sync)
    assert client.post('/api/transtrade/sync',json={'from':'2026-08-01','to':'2026-08-31'},headers=H).status_code==200
    assert calls==[('2026-08-01','2026-08-31')]
    monkeypatch.setattr(server,'user',lambda:dict(id=99,role='logist',vehicles=[]))
    assert client.get('/api/transtrade').status_code==403
    assert client.post('/api/transtrade/sync',json={},headers=H).status_code==403
