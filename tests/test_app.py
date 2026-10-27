import os,tempfile,json,datetime as dt
from pathlib import Path
import pytest
os.environ['FLEET_DATA']=tempfile.mkdtemp(prefix='fleet-tests-')
from app import server
from app.importer import load_excel,SOURCE,hours,vehicle
from app.analytics import report,reconcile
@pytest.fixture(scope='module')
def data():return load_excel()
@pytest.fixture()
def client():
    server.init();c=server.app.test_client()
    with c.session_transaction() as s:s['uid']=1;s['csrf']='test'
    return c
H={'X-CSRF-Token':'test'}
def test_raw_excel_totals(data):
    assert len(data['trips'])==996
    assert sum(r['revenue'] for r in data['trips'])==pytest.approx(13724319.06)
    assert sum(r['payout'] for r in data['trips'])==pytest.approx(6930671.46)
    assert sum(r['km'] for r in data['trips'])==99197
    assert sum(r['hours'] for r in data['trips'])==pytest.approx(9330)
def test_satellite_matches_pivot(data):
    assert sum(r['km'] for r in data['satellite'])==pytest.approx(54294.4)
    assert sum(r['hours'] for r in data['satellite'])==pytest.approx((154*24+8)+26/60+7/3600)
def test_plan_routes_and_totals(data):
    assert len(data['plans'])==1436 and len(data['routes'])==114
    assert sum(r['revenue'] for r in data['plans'])==pytest.approx(20637711.5)
    assert sum(r['payout'] for r in data['plans'])==pytest.approx(10318935)
    assert {r['date'][:7] for r in data['plans']}=={'2026-07','2026-09'}
def test_non_trip_charges_do_not_inflate_work(data):
    t=report(data,{})['totals']
    assert t['trips']==815 and t['km']==94699
    assert t['hours']==pytest.approx(6208.2666666667)
    assert t['average_hours']==pytest.approx(t['hours']/815)
    assert t['revenue']==pytest.approx(13724319.06)
def test_filter_and_actual_days(data):
    t=report(data,{'vehicle':'Т711РМ797','from':'2026-08-01','to':'2026-08-31'})['totals']
    assert t['revenue']==pytest.approx(471437.88,abs=0.001)
    assert t['trips']==40
    assert not report(data,{'from':'2026-09-01','to':'2026-09-30'})['trips']
def test_reconcile_missing_not_zero(data):
    rows=reconcile(data,{})
    assert any(r['sat_km'] is None and r['delta_km'] is None for r in rows)
    for r in rows:
        if r['state']=='Сопоставлено':assert r['delta_km']==pytest.approx(r['tt_km']-r['sat_km'])
def test_status_dedup(data):
    keys=[(r['date'],r['kind'],r['entity'],r['reason']) for r in data['statuses']]
    assert len(keys)==len(set(keys))==181
    assert any('; Блокнот!' in r['source'] for r in data['statuses'])
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
    assert client.delete('/api/manual/'+r['id'],headers=H).status_code==200
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
    assert len(after['plans'])==len(before['plans']) and len(after['trips'])==996
    assert client.post('/api/import',headers=H,json={}).status_code==200
    assert len(client.get('/api/data').json['trips'])==996

def test_carrier_matches_cached_excel_pivot(data):
    t=report(data,{'carrier':'ООО "ЧАРТЕР"'})['totals']
    assert t['revenue']==pytest.approx(5643144.06,abs=0.001)
    assert t['payout']==pytest.approx(1680936.81,abs=0.001) # matches Статистика!Q8, includes unassigned entries
    assigned=sum(r['payout'] for r in data['trips'] if r['carrier']=='ООО \"ЧАРТЕР\"' and r['vehicle'])
    assert assigned==pytest.approx(1613936.81,abs=0.001) # matches Статистика!K8

def test_page_navigation_and_unknown_paths(client):
    for path in ['/analytics/statistics','/analytics/dashboard','/analytics/comparison','/analytics/reconcile','/planning/calendar','/planning/planner','/data/orders','/data/directories','/data/connections','/data/users']:
        response=client.get(path)
        assert response.status_code==200
        assert b'/static/main.js' in response.data
    for path in ['/data/local-login.txt','/analytics/unknown','/planning/users','/api/unknown']:
        assert client.get(path).status_code==404
    # Serving the shell at a deep link does not grant access to its protected data.
    anonymous=server.app.test_client()
    assert anonymous.get('/data/users').status_code==200
    assert anonymous.get('/api/users').status_code==401
