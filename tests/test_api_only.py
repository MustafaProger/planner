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
