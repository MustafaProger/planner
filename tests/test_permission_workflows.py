"""Successful workflows, denial, revision and scope for each explicit capability."""
import json
import pytest
from app import server, workspace as ws, permissions

@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA', tmp_path)
    monkeypatch.setattr(server, 'DB', tmp_path/'fleet.sqlite')
    server.init()
    admin = server.app.test_client()
    with admin.session_transaction() as session:
        session.update(uid=1, csrf='test')
    with server.db() as c:
        car = ws.save_catalog(c, 'vehicles', {'name': 'А001АА77'})
        other = ws.save_catalog(c, 'vehicles', {'name': 'А002АА77'})
        driver = ws.save_catalog(c, 'drivers', {'name': 'Водитель'})
        route = ws.save_catalog(c, 'routes', {'name': 'Маршрут'})
        ws.save_tariff(c, dict(route_id=route, effective_from='2026-01-01', revenue=100, payout=50, partner_payout=60, km=10))
        for ident, vehicle in [('tt',car), ('outside',other)]:
            c.execute('insert into records(id,kind,body) values(?,?,?)', (ident,'trips',ws.dump(dict(id=ident, origin='transtrade', vehicle_id=vehicle, driver_id=driver, date='2026-11-12', category='Рейс', revenue=100, payout=50, km=10))))
    return admin, dict(car=car, other=other, driver=driver, route=route)

@pytest.mark.parametrize('role', ['viewer', 'logist'])
@pytest.mark.parametrize('key', list(permissions.RULES))
def test_capability_positive_then_revoke(context, monkeypatch, role, key):
    admin, ids = context
    headers={'X-CSRF-Token':'test'}
    account=dict(name='Сотрудник',password='isolated-test-password',role=role,vehicles=['А001АА77'])
    rights={k: k == key or (key == 'fuel.write' and k == 'fuel.read') for k in permissions.RULES}
    assert admin.post('/api/users',headers=headers,json={**account,'permissions':rights}).status_code==200
    ident=next(u['id'] for u in admin.get('/api/users').json if u['name']==account['name'])
    member=server.app.test_client()
    assert member.post('/api/login',json=account).status_code==200
    auth={'X-CSRF-Token':member.get('/api/session').json['csrf']}
    day='2026-11-12'
    trip=dict(id='manual-test',start=day+'T09:00',end=day+'T10:00',date=day,vehicle_id=ids['car'],driver_id=ids['driver'],category='Рейс',revenue=100,payout=50,km=10)
    plan=dict(date=day,vehicle_id=ids['car'],driver_id=ids['driver'],route_id=ids['route'])
    status=dict(date=day,kind='vehicle',entity='А001АА77',reason='Ремонт')
    if key.endswith('.delete'):
        kind=key.split('.')[0]; payload={'plans':plan,'trips':trip,'statuses':status}[kind]
        assert admin.post('/api/manual/'+kind,headers=headers,json=payload).status_code==200
        record=next(r for r in server.dataset()[kind] if r.get('origin')=='manual')
        method,path,body='DELETE','/api/manual/'+record['record_id'],record
    elif key in ('plans.write','trips.write','statuses.write'):
        kind=key.split('.')[0];method,path,body='POST','/api/manual/'+kind,{'plans':plan,'trips':trip,'statuses':status}[kind]
    elif key=='trips.classify': method,path,body='PUT','/api/records/tt',dict(category='Доплата',revision=1)
    elif key=='catalog.write': method,path,body='POST','/api/catalog/routes',dict(name='Новый маршрут')
    elif key in ('settings.write','reviews.write'):
        state=member.get('/api/charter?view=workspace').json['state']
        body=dict(revision=state['revision'],kind='settings',settings={'fuel_norms':{'А001АА77':20}}) if key=='settings.write' else dict(revision=state['revision'],kind='review',review=dict(id='QA|А001АА77|'+day,vehicle='А001АА77',status='В работе',comment='Проверка'))
        method,path='PUT','/api/charter/state'
    elif key=='coverage.write':
        preview=member.get('/api/workspace/coverage/preview?source=trips&start='+day+'&end='+day).json
        method,path,body='POST','/api/workspace/coverage',dict(source='trips',start=day,end=day,complete=True,checked_fingerprint=preview['checked_fingerprint'],fingerprint_algorithm=preview['algorithm'])
    elif key=='expenses.write':method,path,body='POST','/api/workspace/expenses',dict(vehicle_id=ids['car'],date=day,category='Ремонт',amount=10)
    elif key=='fuel.write':method,path,body='POST','/api/workspace/card_bindings',dict(vehicle_id=ids['car'],start=day,end=day,provider='rosneft',card='001')
    elif key=='fuel.read':method,path,body='GET','/api/rosneft/driver-assignments',None
    elif key=='connections.run':
        from app import connections
        monkeypatch.setattr(connections,'check_all',lambda:[])
        method,path,body='POST','/api/connections/check',{}
    result=member.open(path,method=method,headers=auth,json=body)
    assert result.status_code==200, result.json
    if key in ('plans.write','trips.write','statuses.write'):
        record=next(r for r in server.dataset()[kind] if r.get('origin')=='manual')
        update={**body,'revision':record['revision'],'note':'Изменено'}
        assert member.put('/api/records/'+record['record_id'],headers=auth,json=update).status_code==200
        outside={**body, 'vehicle_id':ids['other'], 'entity':'А002АА77'}
        assert member.post(path,headers=auth,json=outside).status_code==403
    if key=='trips.classify':
        assert member.get('/api/records/tt').json['category']=='Доплата'
        assert member.put('/api/records/outside',headers=auth,json=body).status_code==403
        assert member.put(path,headers=auth,json=body).status_code==409
    if key in ('coverage.write','expenses.write','fuel.write'):
        row=next(r for r in server.dataset()[{'coverage.write':'coverage','expenses.write':'expenses','fuel.write':'card_bindings'}[key]] if r['id']==result.json['id'])
        assert member.put(path+'/'+row['id'],headers=auth,json={**body,'revision':row['revision'],'note':'Изменено'}).status_code==200
        assert member.delete(path+'/'+row['id'],headers=auth,json={'revision':row['revision']}).status_code==409
        assert member.delete(path+'/'+row['id'],headers=auth,json={'revision':row['revision']+1}).status_code==200
    if key.endswith('.delete'):
        assert admin.post('/api/manual/'+kind,headers=headers,json=payload).status_code==200
    rights[key]=False
    assert admin.put('/api/users/'+str(ident),headers=headers,json={**account,'password':'','permissions':rights}).status_code==200
    assert member.open(path,method=method,headers=auth,json=body).status_code==403
    assert member.get('/api/users').status_code==403
    assert admin.delete('/api/users/'+str(ident),headers=headers).status_code==200
    assert member.get('/api/data').status_code==401


def test_record_details_and_fuel_dependency(context):
    admin, ids=context
    assert server.app.test_client().get('/api/records/tt').status_code==401
    row=admin.get('/api/records/tt').json
    assert row['revision']==1 and row['record_id']=='tt' and row['vehicle']=='А001АА77'
    account=dict(name='Карты',password='isolated-test-password',role='viewer',vehicles=[],permissions={'fuel.write':True,'fuel.read':False})
    assert admin.post('/api/users',headers={'X-CSRF-Token':'test'},json=account).status_code==200
    member=server.app.test_client();member.post('/api/login',json=account)
    auth={'X-CSRF-Token':member.get('/api/session').json['csrf']}
    assert member.post('/api/workspace/card_bindings',headers=auth,json={}).status_code==403
    assert member.put('/api/rosneft/driver-assignments',headers=auth,json={}).status_code==403
