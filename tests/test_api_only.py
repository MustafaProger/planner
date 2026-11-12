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
    login=client.get('/planner')
    assert login.status_code==200
    assert b'<form method="post">' in login.data
    assert b'<script' not in login.data
    assert login.headers['Cache-Control']=='no-store'
    assert login.headers['Referrer-Policy']=='same-origin'
    assert client.get('/api/charter?view=workspace').status_code==401

    password=(tmp_path/'local-login.txt').read_text().splitlines()[1].split(': ',1)[1]
    credentials={'name':'Руководитель','password':password}
    assert client.post('/planner',data=credentials,headers={'Origin':'https://other.invalid'}).status_code==403
    wrong=client.post('/planner',data={**credentials,'password':'wrong'})
    assert wrong.status_code==401 and b'role="alert"' in wrong.data
    response=client.post('/charter/planner',data=credentials,headers={'Origin':'http://localhost'})
    assert response.status_code==303 and response.location=='/planner'
    assert client.get('/').location=='/overview'
    for page in server.CHARTER_PAGES:
        assert client.get('/'+page).status_code==200
        legacy=client.get('/charter/'+page+'?period=month')
        assert legacy.status_code==302 and legacy.location=='/'+page+'?period=month'
    assert client.get('/charter/').location=='/overview'
    assert client.get('/data/orders').location=='/data'
    assert client.get('/charter/unknown').status_code==404
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
    assert b'<form method="post">' in client.get('/planner').data

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


def test_deviation_export_formats_only_submitted_rows(api_only):
    import datetime as dt
    import io
    from openpyxl import load_workbook

    path='/api/charter/deviations/export'
    headers={'X-CSRF-Token':'test'}
    row=['2026-11-05','Е825ОС95','ЧАРТЕР','Водитель','Сигнал','Основание','В работе','=1+1']
    assert server.app.test_client().post(path,json=[row],headers=headers).status_code==401
    assert api_only.post(path,json=[row]).status_code==403
    assert api_only.post(path,json=[row[:-1]],headers=headers).status_code==400
    response=api_only.post(path,json=[row],headers=headers)
    assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    assert response.mimetype.endswith('spreadsheetml.sheet')
    book=load_workbook(io.BytesIO(response.data))
    sheet=book['Отклонения']
    assert sheet.freeze_panes=='A2' and sheet.auto_filter.ref=='A1:H2'
    assert list(sheet.values)[1]==(dt.datetime(2026,11,5),*row[1:])
    assert sheet['H2'].data_type=='s'
    book.close()


def test_user_creation_reads_vehicle_catalog_without_loading_reports(api_only, monkeypatch):
    with server.db() as c:
        ws.add_catalog(c, 'vehicles', 'А001АА77')
        ws.add_catalog(c, 'vehicles', 'А002АА77')

    def report_unavailable(*args, **kwargs):
        pytest.fail('Creating a user must not load the report dataset')

    monkeypatch.setattr(server, 'dataset', report_unavailable)
    headers = {'X-CSRF-Token': 'test'}
    account = dict(name='Новый наблюдатель', password='test-password-only', role='viewer')
    vehicles = ['А001АА77', 'А002АА77']
    invalid = api_only.post('/api/users', headers=headers, json={**account, 'vehicles': [*vehicles, 'Неизвестный']})
    assert invalid.status_code == 400

    created = api_only.post('/api/users', headers=headers, json={**account, 'vehicles': vehicles})
    assert created.status_code == 200
    accounts = api_only.get('/api/users').get_json()
    assert json.loads(next(row['vehicles'] for row in accounts if row['name'] == account['name'])) == vehicles
    assert sum(row['action'] == 'add user' for row in api_only.get('/api/audit').get_json()) == 1

    viewer = server.app.test_client()
    assert viewer.post('/api/login', json=account).status_code == 200
    session = viewer.get('/api/session').get_json()
    assert session['user']['vehicles'] == vehicles
    assert viewer.post('/api/users', headers={'X-CSRF-Token': session['csrf']}, json=account).status_code == 403


def test_user_edit_and_removal_enforce_access_and_revoke_sessions(api_only):
    with server.db() as c:
        ws.add_catalog(c, 'vehicles', 'А001АА77')
        ws.add_catalog(c, 'vehicles', 'А002АА77')
    headers = {'X-CSRF-Token': 'test'}
    original = dict(name='Проверка доступа', password='test-password-only',
                    role='viewer', vehicles=['А001АА77'])
    assert api_only.post('/api/users', headers=headers, json=original).status_code == 200
    account = next(row for row in api_only.get('/api/users').json if row['name'] == original['name'])
    path = f"/api/users/{account['id']}"
    target = server.app.test_client()
    assert target.post('/api/login', json=original).status_code == 200
    target_headers = {'X-CSRF-Token': target.get('/api/session').json['csrf']}
    assert target.put(path, headers=target_headers, json=original).status_code == 403
    assert target.delete(path, headers=target_headers).status_code == 403
    assert api_only.put(path, json=original).status_code == 403
    assert api_only.delete(path).status_code == 403
    assert api_only.delete('/api/users/1', headers=headers).status_code == 409
    assert api_only.put('/api/users/1', headers=headers, json=original).status_code == 409

    edited = dict(name='Обновлённое имя', role='logist', vehicles=['А002АА77'])
    assert api_only.put(path, headers=headers, json={**edited, 'name': 'Руководитель'}).status_code == 400
    assert api_only.put(path, headers=headers, json=edited).status_code == 200
    assert target.get('/api/session').json['user'] == {'id': account['id'], **edited}
    assert target.post('/api/login', json={**edited, 'password': original['password']}).status_code == 200

    new_password = 'new-password-for-test'
    assert api_only.put(path, headers=headers, json={**edited, 'password': new_password}).status_code == 200
    assert target.get('/api/data').status_code == 401
    assert target.post('/api/login', json={**edited, 'password': original['password']}).status_code == 401
    assert target.post('/api/login', json={**edited, 'password': new_password}).status_code == 200
    assert api_only.delete(path, headers=headers).status_code == 200
    assert api_only.delete(path, headers=headers).status_code == 404
    assert api_only.put(path, headers=headers, json=edited).status_code == 404
    assert target.get('/api/data').status_code == 401
    assert target.post('/api/login', json={**edited, 'password': new_password}).status_code == 401

    assert api_only.post('/api/users', headers=headers, json={**edited, 'password': new_password}).status_code == 200
    rows = api_only.get('/api/users').json
    assert all(row['id'] != account['id'] and 'password' not in row and 'session_version' not in row for row in rows)
    assert target.get('/api/data').status_code == 401
    actions = [row['action'] for row in api_only.get('/api/audit').json]
    assert actions == ['add user', 'delete user', 'edit user', 'edit user', 'add user']
