import copy,json,sqlite3
from pathlib import Path
import pytest
from app import workspace as w,reports
from app.fuel_history import persist,normalized
ADMIN={'id':1,'role':'admin','vehicles':[]}
@pytest.fixture
def source():
    rate=dict(id='R1',group='Почта',revenue=1000,payout=400,partner_payout=600,km=100,hours=4,rate=100,partner_rate=150)
    car='А123АА777';driver='Иванов'
    return dict(vehicles={car:'Чартер ООО'},vehicle_details={car:dict(brand='Газель',company='Чартер ООО')},drivers={driver:'Чартер ООО'},routes=[rate],
      trips=[dict(id='1',date='2026-08-01',start='2026-08-01T08:00:00',end='2026-08-01T12:00:00',vehicle=car,driver=driver,client='Клиент',carrier='Компания',type='Газель',payment='Безнал',payout_method='Нал',revenue=900,payout=400,km=90,hours=4,category='Рейс',source='ТТ!2')],
      plans=[dict(id='excel:2',date='2026-07-01',vehicle=car,driver=driver,route='R1',partner=False,revenue=1000,payout=400,km=100,hours=4,source='Логист!2')],statuses=[],satellite=[],meta={'files':[],'counts':{},'issues':[]})
@pytest.fixture
def c(source):
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;w.initialize(c,source);return c

def plan(c,date='2026-09-01',**kw):
    d=w.dataset(c);return dict(date=date,route_id=d['directories']['routes'][0]['id'],vehicle_id=d['directories']['vehicles'][0]['id'],driver_id=d['directories']['drivers'][0]['id'],**kw)

def test_seed_separates_brand_company(c):
    r=w.dataset(c)['directories']['vehicles'][0];assert r['brand']=='Газель' and r['company']=='Чартер ООО'

def test_tariff_effective_date_and_freeze(c,source):
    b=plan(c);w.create_records(c,'plans',b,ADMIN)
    w.save_tariff(c,dict(source['routes'][0],route_id=b['route_id'],effective_from='2026-09-02',revenue=2000))
    w.create_records(c,'plans',dict(b,date='2026-09-02'),ADMIN)
    d=w.dataset(c);assert [r['revenue'] for r in d['plans']]==[1000,1000,2000]
    source['routes'][0]['revenue']=3000;w.ingest(c,source);assert [r['revenue'] for r in w.dataset(c)['plans']]==[1000,1000,2000]
    with pytest.raises(ValueError):w.save_tariff(c,dict(source['routes'][0],route_id=b['route_id'],effective_from='2026-09-02'))

def test_no_route_and_duplicate_not_counted(c,source):
    source['plans'].append(dict(source['plans'][0],id='excel:3',source='Логист!3'))
    source['routes'].append(dict(source['routes'][0],id='нет марш'))
    source['plans'].append(dict(source['plans'][0],id='excel:4',route='нет марш',km=1302,revenue=0))
    w.ingest(c,source);d=w.dataset(c);assert len(d['plans'])==3
    assert reports.plan_rows(d,{})['totals']==[]
    duplicate=d['plans'][0];w.edit_record(c,duplicate['id'],dict(duplicate,slot='1'),ADMIN)
    assert reports.plan_rows(w.dataset(c),{})['totals'][0]['revenue']==2000

def test_nonoverlapping_period_no_delta_and_explicit_zero(c):
    q={'from':'2026-07-01','to':'2026-08-31'}
    assert reports.comparison(w.dataset(c),q)['rows'][0]['delta_revenue'] is None
    for source in ('plans','trips'):w.save_extra(c,'coverage',dict(start=q['from'],end=q['to'],source=source,complete=True),ADMIN)
    assert reports.comparison(w.dataset(c),q)['rows'][0]['delta_revenue']==-100
    q['from']='2026-08-01'
    row=reports.comparison(w.dataset(c),q)['rows'][0];assert row['plan_revenue']==0 and row['state']=='Вне плана'

def test_renames_references_and_companies(c):
    d=w.dataset(c);r=d['directories']['drivers'][0]
    w.save_catalog(c,'drivers',dict(r,name='Иванов Иван'),r['id'])
    assert w.dataset(c)['plans'][0]['driver']=='Иванов Иван'
    company=d['directories']['companies'][0];w.save_catalog(c,'companies',dict(company,name='Новая компания'),company['id'])
    assert w.dataset(c)['directories']['vehicles'][0]['company']=='Новая компания'
    with pytest.raises(ValueError):w.save_catalog(c,'drivers',dict(r,name='Другой'),r['id'])

def test_reimport_history_and_manual_collision(c,source):
    b=plan(c);w.create_records(c,'plans',b,ADMIN);manual=w.dataset(c)['plans'][-1]
    source['plans']=[dict(manual,id='excel:2',source='Логист!2')]
    w.ingest(c,source);w.ingest(c,source)
    assert len(w.dataset(c)['plans'])==2

def test_revision_permissions_and_invalid_numbers(c):
    b=plan(c);log={'id':2,'role':'logist','vehicles':[]}
    with pytest.raises(PermissionError):w.create_records(c,'plans',b,log)
    with pytest.raises(ValueError):w.save_extra(c,'expenses',dict(vehicle_id=b['vehicle_id'],date=b['date'],category='Ремонт',amount=float('nan')),ADMIN)
    with pytest.raises(ValueError):w.create_records(c,'plans',dict(b,weekdays=[]),ADMIN)
    r=w.dataset(c)['plans'][0]
    with pytest.raises(ValueError):w.edit_record(c,r['id'],dict(r,revision=0),ADMIN)

def test_unique_status_days_and_overlap(c):
    car=w.dataset(c)['directories']['vehicles'][0]
    for reason in ('Сервис','Ремонт'):
        w.create_records(c,'statuses',dict(date='2026-08-01',kind='vehicle',entity_id=car['id'],reason=reason),ADMIN)
    r=reports.downtime(w.dataset(c),{})['rows'][0]
    assert r['status_days']==1 and r['overlap_days']==1 and len(r['reasons'])==2

def test_manual_actual_edit_import_idempotence(c,source):
    b=dict(source['trips'][0],id='manual-2');assert w.create_records(c,'trips',b,ADMIN)==1
    r=w.dataset(c)['trips'][-1];w.edit_record(c,r['record_id'],dict(r,revenue=1234),ADMIN)
    source['trips']=[dict(b,revenue=9999)];w.ingest(c,source)
    d=w.dataset(c);assert len(d['trips'])==2 and d['trips'][-1]['revenue']==1234

def test_category_override_survives_repeated_imports(c,source):
    r=w.dataset(c)['trips'][0];w.edit_record(c,r['record_id'],dict(category='Удержание',revision=r['revision']),ADMIN)
    w.ingest(c,source);w.ingest(c,source)
    assert w.dataset(c)['trips'][0]['category']=='Удержание'

def fuel_row(day,amount='100',typ='11'):
    return dict(dateRec=day+'T12:00:00',typeNumber=typ,costClient=amount,amount='10',serviceName='ГАЗ',currencyName='Рубли',cardNumber='card1')
def test_fuel_history_refund_and_interval_replacement(tmp_path):
    def save(a,b,rows):persist(tmp_path,dict(provider='neftm',synced_at='now',**{'from':a,'to':b},rows=rows))
    save('2026-08-01','2026-08-31',[fuel_row('2026-08-01'),fuel_row('2026-08-02','20','24')])
    save('2026-09-01','2026-09-30',[fuel_row('2026-09-01')])
    save('2026-09-01','2026-09-30',[fuel_row('2026-09-01','200')])
    ops,_=normalized(tmp_path);assert len(ops)==3 and sum(r['amount'] for r in ops)==280
    assert ops[1]['liters']==-10

def test_card_binding_dates_overlap_expenses_and_no_guessed_allocation(c,tmp_path):
    persist(tmp_path,dict(provider='neftm',synced_at='now',**{'from':'2026-08-01','to':'2026-08-31'},rows=[fuel_row('2026-08-01'),fuel_row('2026-08-02')]))
    car=plan(c)['vehicle_id'];b=dict(start='2026-08-01',end='2026-08-01',provider='neftm',card='card1',vehicle_id=car)
    w.save_extra(c,'card_bindings',b,ADMIN)
    with pytest.raises(ValueError):w.save_extra(c,'card_bindings',b,ADMIN)
    w.save_extra(c,'expenses',dict(date='2026-08-01',vehicle_id=car,category='Ремонт',amount=50),ADMIN)
    r=reports.economics(w.dataset(c),{'from':'2026-08-01','to':'2026-08-31'},tmp_path)
    assert r['unassigned']==1 and r['rows'][0]['known_cost_balance']==350

def test_merge_keeps_status_provenance_and_delete(c):
    other=w.save_catalog(c,'drivers',dict(name='Иванов И.'))
    original=w.dataset(c)['directories']['drivers'][0]['id']
    for ident in (other,original):w.create_records(c,'statuses',dict(date='2026-08-01',kind='driver',entity_id=ident,reason='Сервис'),ADMIN)
    w.merge_catalog(c,'drivers',other,original);r=w.dataset(c)['statuses'][0];assert len(r['related_ids'])==1
    w.edit_record(c,r['id'],{},ADMIN,delete=True);assert not w.dataset(c)['statuses']

def test_http_workspace_auth_validation_revision_and_backup(tmp_path,monkeypatch,source):
    from app import server
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server,'DB',tmp_path/'fleet.sqlite');monkeypatch.setattr(server,'load_excel',lambda:source)
    server.init();client=server.app.test_client();h={'X-CSRF-Token':'test'}
    assert client.post('/api/catalog/clients',json={'name':'New'},headers=h).status_code==401
    with client.session_transaction() as s:s.update(uid=1,csrf='test')
    assert client.post('/api/catalog/clients',json={'name':'New'}).status_code==403
    assert client.post('/api/catalog/clients',json=[],headers=h).status_code==400
    assert client.post('/api/workspace/coverage',json={'source':'plans','start':'2026-01-01','end':'2026-01-31','complete':'false'},headers=h).status_code==400
    result=client.post('/api/catalog/clients',json={'name':'New'},headers=h);assert result.status_code==200
    assert client.put('/api/catalog/clients/'+result.json['id'],json={'name':'Changed','revision':0},headers=h).status_code==400
    assert client.get('/api/workspace/report?mode=comparison&from=2026-07-01&to=2026-08-31').json['rows'][0]['delta_revenue'] is None
    for route in ['analytics/planreport','analytics/economics','analytics/downtime','analytics/telemetry','data/quality','data/coverage','data/expenses','data/fuelcards']:assert client.get('/'+route).status_code==200
    with sqlite3.connect(tmp_path/'before-workspace-v2.sqlite') as backup:
        restored=json.loads(backup.execute('select body from snapshot').fetchone()[0]);assert restored['trips']==source['trips']
    monkeypatch.setattr(server,'user',lambda:{'id':2,'role':'logist','vehicles':[]})
    assert client.post('/api/catalog/clients',json={'name':'Denied'},headers=h).status_code==403
    assert client.post('/api/manual/plans',json={'date':'2026-09-01','route':'R1','vehicle':'А123АА777','driver':'Иванов'},headers=h).status_code==403
    assert 'operations' not in client.get('/api/workspace/report?mode=economics').json
