"""API-only boundary: old files cannot enter reports or be uploaded."""
import json
import pytest
from app import server, workspace as ws

@pytest.fixture
def api_only(tmp_path, monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path)
    monkeypatch.setattr(server,'DB',tmp_path/'fleet.sqlite')
    monkeypatch.setenv('FLEET_EXCEL_DIR',str(tmp_path/'missing-books'))
    server.init()
    client=server.app.test_client()
    with client.session_transaction() as s:
        s['uid']=1;s['csrf']='test'
    return client

def test_empty_install_and_retired_routes(api_only):
    data=api_only.get('/api/data').get_json()
    assert data['trips']==[] and data['satellite']==[]
    assert data['meta']['source']=='API'
    for path in ['/api/import','/api/evidence/mileage/preview','/api/evidence/mileage/confirm']:
        assert api_only.post(path,headers={'X-CSRF-Token':'test'}).status_code in (404,405)
    for path in ['/settings/excel','/analytics/telemetry','/data/telemetry']:
        assert api_only.get(path).status_code==404

def test_legacy_rows_not_used_and_database_preserved(api_only,monkeypatch):
    trip=dict(id='1',date='2026-08-01',vehicle='А001АА77',category='Рейс',km=None,revenue=10,payout=5,hours=1)
    with server.db() as c:
        for ident,origin,kind in [('old','excel','trips'),('api','transtrade','trips'),('local','manual','trips'),('sat','excel','satellite')]:
            row=dict(trip,origin=origin,legacy_snapshot=dict(km=93),id=ident)
            c.execute('insert into records(id,kind,body) values(?,?,?)',(ident,kind,json.dumps(row)))
    from app import monitoring_history
    monkeypatch.setattr(monitoring_history,'daily_rows',lambda *a:[])
    data=server.dataset()
    assert {r['id'] for r in data['trips']}=={'api','local'}
    assert all('legacy_snapshot' not in r for r in data['trips'])
    assert data['satellite']==[] and data['satellite_raw']==[]
    assert all(r['km'] is None for r in data['trips'])
    with server.db() as c:
        assert c.execute('select count(*) from records').fetchone()[0]==4
    monkeypatch.setattr(monitoring_history,'daily_rows',lambda *a:[dict(vehicle='А001АА77',date='2026-08-01',km=42,engine_hours=2,fuel_liters=None,mileage_status='ok',fuel_status='missing',synced_at='now')])
    data=server.dataset()
    assert data['satellite'][0]['km']==42
    assert data['satellite'][0]['hours'] is None
    assert data['satellite'][0]['sources']['km']=='ГЛОНАССсофт API'

def test_charter_html_login_and_private_workspace(api_only, tmp_path):
    client=server.app.test_client()
    login=client.get('/charter/planner')
    assert login.status_code==200
    assert b'<form method="post">' in login.data
    assert b'<script' not in login.data
    assert login.headers['Cache-Control']=='no-store'
    assert login.headers['Referrer-Policy']=='same-origin'
    assert client.get('/api/charter?view=workspace').status_code==401

    password=(tmp_path/'local-login.txt').read_text().splitlines()[1].split(': ',1)[1]
    credentials={'name':'Руководитель','password':password}
    assert client.post('/charter/planner',data=credentials,headers={'Origin':'https://other.invalid'}).status_code==403
    wrong=client.post('/charter/planner',data={**credentials,'password':'wrong'})
    assert wrong.status_code==401 and b'role="alert"' in wrong.data
    response=client.post('/charter/planner',data=credentials,headers={'Origin':'http://localhost'})
    assert response.status_code==303 and response.location=='/charter/planner'
    shell=client.get(response.location)
    assert b'id="root"' in shell.data and shell.headers['Cache-Control']=='no-store'
    for path in (server.ROOT/'app/static/charter/assets').glob('*.js'):
        asset=client.get('/static/charter/assets/'+path.name)
        assert asset.headers['Cache-Control']=='public, max-age=31536000, immutable'
        assert 'Set-Cookie' not in asset.headers

    workspace=client.get('/api/charter?view=workspace')
    assert workspace.status_code==200 and workspace.json['user']['role']=='admin'
    csrf=workspace.headers['X-CSRF-Token']
    assert csrf and csrf.encode() not in workspace.data
    assert workspace.headers['Cache-Control']=='no-store'
    assert client.post('/api/logout').status_code==403
    assert client.post('/api/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    assert client.get('/api/charter?view=workspace').status_code==401
    assert b'<form method="post">' in client.get('/charter/planner').data

def test_charter_projection_preserves_catalog_merges_and_coverage(api_only):
    from app.coverage import ALGORITHM, fingerprint
    with server.db() as c:
        old=ws.save_catalog(c,'vehicles',{'name':'А001АА77','aliases':['Прежнее название']})
        new=ws.save_catalog(c,'vehicles',{'name':'А002АА77'})
        ws.merge_catalog(c,'vehicles',old,new)
        trip=dict(id='r',vehicle='Прежнее название',date='2026-11-01',category='Рейс',
                  km=None,revenue=100,payout=50,load_address='Исходное поле')
        c.execute("insert into records(id,kind,body) values('r','trips',?)",(ws.dump(trip),))
        day=trip['date']
        coverage=dict(source='trips',start=day,end=day,checked_complete=True,fingerprint_algorithm=ALGORITHM)
        coverage['checked_fingerprint']=fingerprint(ws.dataset(c),'trips',day,day)
        c.execute("insert into coverage(id,body) values('period',?)",(ws.dump(coverage),))
        full=ws.dataset(c)
        compact=ws.dataset(c,charter_view=True)
        assert full['coverage']==compact['coverage'] and compact['coverage'][0]['complete']
        assert compact['trips'][0]['vehicle']=='А002АА77'
        assert compact['trips'][0]['revenue']==100 and compact['trips'][0]['km'] is None
        assert 'load_address' in full['trips'][0] and 'load_address' not in compact['trips'][0]
