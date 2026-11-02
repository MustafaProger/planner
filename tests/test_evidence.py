import datetime as dt
import io
import json
import sqlite3
import threading
import pytest
from app import mileage,shifts,workspace as ws

@pytest.fixture
def c():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    ws.schema(conn);mileage.schema(conn);shifts.schema(conn)
    for kind,ident,name in [('vehicles','v1','А123АА'),('vehicles','v2','В456ВВ'),('drivers','d1','Первый'),('drivers','d2','Второй')]:
        conn.execute('insert into catalog(id,kind,body) values(?,?,?)',(ident,kind,json.dumps({'name':name,'resource_type':'vehicle'})))
    for ident,number,veh in [('1','N1','v1'),('2','N2','v1')]:
        row=dict(origin='transtrade',id=ident,provider_id=ident,number=number,date='2026-08-01',start='2026-08-01T08:00:00',end='2026-08-01T12:00:00',vehicle_id=veh,driver_id='d1',cancelled=False,km=None,revenue=1000,payout=100,category='Рейс',hours=4)
        conn.execute('insert into records(id,kind,body) values(?,?,?)',(ident,'trips',json.dumps(row)))
    yield conn
    conn.close()

def content(km='93,5',ident='1'):
    return f'provider_id;date;vehicle;km\n{ident};2026-08-01;А123АА;{km}\n'.encode()

ASOF='2026-08-02T11:00:00+03:00'
def accept(c,data=None,asof=ASOF):
    data=data or content();p=mileage.preview(c,data,'test.csv',asof,'ТТ отчет 1')
    return mileage.apply(c,data,'test.csv',asof,'ТТ отчет 1',p['token'],1)

def test_mileage_repeat_newer_older_and_history(c):
    assert accept(c)['applied']==1
    assert accept(c)['unchanged']==1
    assert accept(c,content('101'),'2026-08-03T11:00:00+03:00')['applied']==1
    assert accept(c,content('12'))['older']==1
    assert c.execute('select count(*) from mileage_observations').fetchone()[0]==2
    rows=mileage.enrich(c,mileage.trips(c));assert rows[0]['km']==101
    assert rows[0]['revenue']==1000 and rows[1]['km'] is None

@pytest.mark.parametrize('value',['','NaN','inf','-1'])
def test_invalid_distinct_from_zero(c,value):
    p=mileage.preview(c,content(value),'a.csv',ASOF,'ТТ')
    assert p['rows'][0]['status']=='invalid'

def test_zero_is_fact_and_timestamp_conflict(c):
    assert accept(c,content('0'))['applied']==1
    p=mileage.preview(c,content('2'),'a.csv',ASOF,'ТТ')
    assert p['rows'][0]['status']=='conflict'
    with pytest.raises(ValueError):mileage.apply(c,content('2'),'a.csv',ASOF,'ТТ',p['token'],1)
    assert mileage.enrich(c,mileage.trips(c))[0]['km']==0

def test_stale_preview_and_identity(c):
    p=mileage.preview(c,content(),'a.csv',ASOF,'ТТ')
    row=json.loads(c.execute("select body from records where id='1'").fetchone()[0]);row['vehicle_id']='v2'
    c.execute("update records set body=? where id='1'",(json.dumps(row),))
    with pytest.raises(mileage.Conflict):mileage.apply(c,content(),'a.csv',ASOF,'ТТ',p['token'],1)
    row['vehicle_id']='v1';c.execute("update records set body=? where id='1'",(json.dumps(row),));accept(c)
    row['end']='2026-08-01T13:00:00';c.execute("update records set body=? where id='1'",(json.dumps(row),))
    enriched=mileage.enrich(c,mileage.trips(c))[0]
    assert enriched['km'] is None and enriched['km_observation']['status']=='stale'

def test_number_match_is_not_id_and_ambiguous_rejected(c):
    data=b'number;date;vehicle;km\n1;2026-08-01;AA;4\n'
    assert mileage.preview(c,data,'a.csv',ASOF,'TT')['rows'][0]['status']=='invalid'
    data='number;date;vehicle;km\nN1;2026-08-01;А123АА;4\n'.encode()
    assert mileage.preview(c,data,'a.csv',ASOF,'TT')['ready']==1
    row=json.loads(c.execute("select body from records where id='2'").fetchone()[0]);row['number']='N1'
    c.execute("update records set body=? where id='2'",(json.dumps(row),))
    assert mileage.preview(c,data,'a.csv',ASOF,'TT')['ready']==0

def test_xlsx_and_no_duplicate_orders(c):
    from openpyxl import Workbook
    book=Workbook();book.active.append(['provider_id','date','vehicle','km']);book.active.append(['1',dt.datetime(2026,8,1),'А123АА',0])
    stream=io.BytesIO();book.save(stream)
    p=mileage.preview(c,stream.getvalue(),'a.xlsx',ASOF,'TT');assert p['ready']==1
    mileage.apply(c,stream.getvalue(),'a.xlsx',ASOF,'TT',p['token'],1)
    assert c.execute('select count(*) from records').fetchone()[0]==2

def shift(c,**overrides):
    return shifts.save(c,dict(driver_id='d1',vehicle_id='v1',start='2026-08-01T00:00:00+03:00',end='2026-08-02T03:00:00+03:00',source_ref='Табель 1',confirmed=True,**overrides),1)

def measurement(start='2026-08-01T00:00:00+03:00',end='2026-08-02T00:00:00+03:00',**extra):
    return dict(vehicle_id='v1',start=start,end=end,km=100,engine_hours=8,**extra)

def test_27_hours_and_conservation(c):
    r=shift(c);assert r['hours']==27
    allocation=shifts.allocate(shifts.rows(c),[measurement()])
    assert allocation['totals']['km']==dict(available=100,assigned=100,unassigned=0)
    assert allocation['measurements'][0]['driver_id']=='d1'

def test_split_drivers_no_daily_prorating(c):
    shifts.save(c,dict(driver_id='d1',vehicle_id='v1',start='2026-08-01T00:00:00+03:00',end='2026-08-01T12:00:00+03:00',source_ref='Табель',confirmed=True),1)
    shifts.save(c,dict(driver_id='d2',vehicle_id='v1',start='2026-08-01T12:00:00+03:00',end='2026-08-02T00:00:00+03:00',source_ref='Табель',confirmed=True),1)
    result=shifts.allocate(shifts.rows(c),[measurement()]);assert result['totals']['km']['unassigned']==100
    intervals=[measurement(end='2026-08-01T12:00:00+03:00'),measurement(start='2026-08-01T12:00:00+03:00')]
    result=shifts.allocate(shifts.rows(c),intervals)
    assert [r['driver_id'] for r in result['measurements']]==['d1','d2']
    assert result['totals']['km']==dict(available=200,assigned=200,unassigned=0)

def test_overlap_driver_different_cars_no_assignment(c):
    shift(c)
    shifts.save(c,dict(driver_id='d1',vehicle_id='v2',start='2026-08-01T00:00:00+03:00',end='2026-08-02T00:00:00+03:00',source_ref='Табель',confirmed=True),1)
    assert all(s['status']=='conflict' for s in shifts.rows(c))
    assert shifts.allocate(shifts.rows(c),[measurement()])['totals']['km']['assigned']==0

def test_revisions_and_history(c):
    r=shift(c);b=dict(r,confirmed=True);updated=shifts.save(c,b,1,r['id'])
    with pytest.raises(mileage.Conflict):shifts.delete(c,r['id'],r['revision'],1)
    shifts.delete(c,r['id'],updated['revision'],1)
    assert shifts.rows(c)==[]
    assert c.execute('select count(*) from actual_shift_history').fetchone()[0]==3

def test_unknown_boundaries_and_overlapping_measurements(c):
    shift(c)
    assert shifts.allocate(shifts.rows(c),[dict(vehicle_id='v1',km=10)])['totals']['km']['unassigned']==10
    result=shifts.allocate(shifts.rows(c),[measurement(),measurement()])
    assert result['totals']['km']['assigned']==0

def test_api_roles_csrf_and_preview_commit(c):
    from flask import Flask,jsonify,session,request
    from app.evidence_routes import register
    from contextlib import contextmanager
    import functools
    @contextmanager
    def db():
        try:yield c;c.commit()
        except Exception:c.rollback();raise
    def auth(roles=None):
        def decorator(fn):
            @functools.wraps(fn)
            def wrapped(*args,**kwargs):
                if not session.get('uid'):return jsonify(error='login'),401
                if roles and session['role'] not in roles:return jsonify(error='role'),403
                if request.method!='GET' and request.headers.get('X-CSRF-Token')!='token':return jsonify(error='csrf'),403
                return fn(*args,**kwargs)
            return wrapped
        return decorator
    app=Flask(__name__);app.secret_key='test';app.testing=True
    app.errorhandler(ValueError)(lambda e:(jsonify(error=str(e)),400))
    register(app,db,lambda:{'satellite':[],'directories':{'vehicles':[]}},auth,lambda *args:None,threading.Lock())
    client=app.test_client();c.commit()
    assert client.post('/api/evidence/shifts',json={}).status_code==401
    with client.session_transaction() as s:s.update(uid=1,role='viewer')
    assert client.post('/api/evidence/shifts',json={}).status_code==403
    with client.session_transaction() as s:s['role']='admin'
    assert client.post('/api/evidence/shifts',json={}).status_code==403
    def form():return dict(file=(io.BytesIO(content()),'a.csv'),source_as_of=ASOF,source_ref='TT')
    headers={'X-CSRF-Token':'token'}
    p=client.post('/api/evidence/mileage/preview',data=form(),headers=headers);assert p.status_code==200
    data=form();data.update(token=p.json['token'],confirmed='true')
    assert client.post('/api/evidence/mileage/confirm',data=data,headers=headers).json['applied']==1
    data=form();data.update(token=p.json['token'],confirmed='true')
    assert client.post('/api/evidence/mileage/confirm',data=data,headers=headers).status_code==409

def test_empty_measurement_is_unknown_not_zero():
    result=shifts.allocate([],[])
    assert all(v['available'] is None for v in result['totals'].values())

def test_driver_changes_cars_with_disjoint_intervals(c):
    shifts.save(c,dict(driver_id='d1',vehicle_id='v1',start='2026-08-01T00:00:00+03:00',end='2026-08-01T12:00:00+03:00',source_ref='Табель',confirmed=True),1)
    shifts.save(c,dict(driver_id='d1',vehicle_id='v2',start='2026-08-01T12:00:00+03:00',end='2026-08-02T00:00:00+03:00',source_ref='Табель',confirmed=True),1)
    a=measurement(end='2026-08-01T12:00:00+03:00');b=measurement(start='2026-08-01T12:00:00+03:00');b['vehicle_id']='v2'
    result=shifts.allocate(shifts.rows(c),[a,b])
    assert result['totals']['km']==dict(available=200,assigned=200,unassigned=0)
    assert [r['driver_id'] for r in result['measurements']]==['d1','d1']

def test_real_sync_preserves_supplement_and_coverage_invalidation():
    from tests.test_workspace import source as source_fixture,confirmation
    from tests.test_transtrade import raw
    from app import transtrade,coverage,analytics
    source=source_fixture.__wrapped__()
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;ws.initialize(c,source,[])
    transtrade.apply(c,[raw()],'2026-08-01','2026-08-31')
    data='provider_id;date;vehicle;km\n1;2026-08-01;А123АА777;100\n'.encode()
    before=coverage.fingerprint(ws.dataset(c),'trips','2026-08-01','2026-08-31')
    accept(c,data)
    after=coverage.fingerprint(ws.dataset(c),'trips','2026-08-01','2026-08-31');assert after!=before
    assert transtrade.apply(c,[raw()],'2026-08-01','2026-08-31')['unchanged']==1
    assert ws.dataset(c)['trips'][0]['km']==100
    assert coverage.fingerprint(ws.dataset(c),'trips','2026-08-01','2026-08-31')==after
    d=ws.dataset(c);d['satellite']=[dict(vehicle=d['trips'][0]['vehicle'],date='2026-08-01',km=90)]
    assert analytics.reconcile(d,{})[0]['delta_km']==10
    raw_new=dict(raw(),BeginDateTime='2026-08-02 08:00:00')
    transtrade.apply(c,[raw_new],'2026-08-01','2026-08-31')
    assert ws.dataset(c)['trips'][0]['km'] is None
    c.close()

def test_placeholder_driver_cannot_confirm_actual_shift(c):
    c.execute("update catalog set body=? where id='d1'",(json.dumps(dict(name='Заменить',placeholder=True)),))
    with pytest.raises(ValueError,match='действующего водителя'):shift(c)
    assert shifts.rows(c)==[]

def test_xlsx_10001_rows_exceeds_limit():
    from openpyxl import Workbook
    book=Workbook(write_only=True);sheet=book.create_sheet();sheet.append(['provider_id','date','vehicle','km'])
    for i in range(10001):sheet.append([str(i),'2026-08-01','А123АА',1])
    stream=io.BytesIO();book.save(stream)
    with pytest.raises(ValueError,match='10000'):mileage.parse(stream.getvalue(),'a.xlsx')

def test_direct_evidence_page_and_current_navigation_are_served_in_isolated_app(tmp_path):
    import os,subprocess,sys
    # A fresh interpreter prevents imports/configuration of the live application's data directory.
    script='''
from app import server
server.user=lambda:None
client=server.app.test_client()
pages={
 'analytics':['dashboard','statistics','comparison','reconcile','planreport','downtime','economics'],
 'planning':['calendar','planner'],
 'data':['orders','monitoringdata','telemetry','neftmdata','rosneftdata','directories'],
 'control':['quality','coverage','fuelcards','expenses','evidence'],
 'settings':['connections','excel','users'],
 'help':['guide'],
}
for section,items in pages.items():
 for name in items:
  response=client.get('/'+section+'/'+name)
  assert response.status_code==200,(section,name,response.status_code)
  assert b'/static/main.js' in response.data
for _ in range(2):
 response=client.get('/control/evidence?from=2026-08-01&to=2026-08-31')
 assert response.status_code==200 and b'/static/evidence.js' in response.data
assert client.head('/control/evidence').status_code==200
assert client.get('/static/evidence.js').status_code==200
assert client.get('/api/evidence').status_code==401
for path in ['/data/evidence','/control/unknown','/control/local-login.txt']:
 assert client.get(path).status_code==404
'''
    result=subprocess.run([sys.executable,'-c',script],env=dict(os.environ,FLEET_DATA=str(tmp_path),FLEET_SCHEDULER='disabled'),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
