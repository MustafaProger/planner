import copy,json,sqlite3
from pathlib import Path
import pytest
from app import transtrade as t,workspace as w,analytics,reports
from tests.test_workspace import source,c,ADMIN


def raw(ident='1',**kw):
    return dict(ID=ident,Number='',BeginDateTime='2026-08-01 08:00:00',EndDateTime='2026-08-01 12:00:00',TransportNumber='А123АА777',Driver='Иванов',Client='Клиент',Worker='Компания',AutoType='Газель',ClientSum='1000.50',WorkerSum='400',Status='',**kw)

def apply(c,rows):return t.apply(c,rows,'2026-08-01','2026-08-31')

def test_real_fields_null_km_and_finances():
    r=t.normalize(raw(ClientPaidSum='10',ProfitSum='600.50',Load='Адрес',User='Логист'))
    assert r['id']=='1' and r['number']=='' and r['km'] is None
    assert r['hours']==4 and r['revenue']==1000.5 and r['financial_source']['ProfitSum']==600.5
    assert r['load_address']=='Адрес' and r['logist']=='Логист'
    x=raw();x['ClientSum']='';x['EndDateTime']='';r=t.normalize(x)
    assert r['revenue'] is None and r['hours'] is None

@pytest.mark.parametrize('change',[{'ID':''},{'BeginDateTime':''},{'ClientSum':'NaN'},{'WorkerSum':True}])
def test_bad_row_rejected(change):
    with pytest.raises(ValueError):t.normalize(dict(raw(),**change))

def test_upsert_preserves_category_history_and_excel_import(c,source):
    old=w.dataset(c)['trips'][0];w.edit_record(c,old['record_id'],{'revision':old['revision'],'category':'Сервис'},ADMIN)
    a=apply(c,[raw()]);assert a['updated']==1
    r=w.dataset(c)['trips'][0];assert r['category']=='Сервис' and r['legacy_snapshot']['km']==90
    assert r['revenue']==1000.5 and r['km'] is None
    assert apply(c,[raw()])['unchanged']==1
    assert w.dataset(c)['trips'][0]['revision']==r['revision']
    w.ingest(c,source);assert w.dataset(c)['trips'][0]['revenue']==1000.5
    apply(c,[dict(raw(),ClientSum='2000',BeginDateTime='2026-08-02 08:00:00')]);r=w.dataset(c)['trips'][0]
    assert r['date']=='2026-08-02' and r['revenue']==2000 and r['category']=='Сервис'
    assert c.execute('select count(*) from transtrade_history').fetchone()[0]>=2


def test_manual_collision_and_absent_response_keep_data(c):
    original=w.dataset(c)['trips'][0]
    b=dict(original,id='2',origin='manual',user_edited=True)
    c.execute("insert into records(id,kind,body) values('manual2','trips',?)",(w.dump(b),))
    before=c.execute("select body from records where id='manual2'").fetchone()[0]
    assert apply(c,[raw('2')])['conflicts']==1
    assert c.execute("select body from records where id='manual2'").fetchone()[0]==before
    assert len(w.dataset(c)['trips'])==2
    assert w.dataset(c)['trips'][0]['api_missing']
    assert c.execute("select count(*) from transtrade_orders").fetchone()[0]==1


def test_missing_then_returns_clears_flag(c):
    apply(c,[raw()]);apply(c,[]);assert w.dataset(c)['trips'][0]['api_missing']
    apply(c,[raw()]);assert not w.dataset(c)['trips'][0].get('api_missing')


def test_cancellation_excluded_and_reactivation(c):
    apply(c,[dict(raw(),Status='Отменён')]);d=w.dataset(c)
    assert len(d['trips'])==1 and analytics.report(d,{})['totals']=={}
    assert reports.downtime(d,{})['rows']==[]
    apply(c,[raw()]);assert analytics.report(w.dataset(c),{})['totals']['trips']==1


def test_null_totals_and_partial_reconciliation():
    rows=[t.normalize(raw()),dict(t.normalize(raw('2')),km=10,revenue=None)]
    a=analytics.aggregate(rows,'vehicle')[0]
    assert a['km'] is None and a['revenue'] is None and a['balance'] is None and a['rub_km'] is None
    assert a['known_sums']['km']==10 and a['missing']['km']==1
    r=analytics.reconcile(dict(trips=rows,satellite=[dict(date='2026-08-01',vehicle=rows[0]['vehicle'],km=100)]),{})[0]
    assert r['delta_km'] is None and r['state']=='Нет пробега ТТ'


def test_refresh_invalidates_completeness(c):
    w.save_extra(c,'coverage',dict(start='2026-08-01',end='2026-08-31',source='trips',complete=True),ADMIN)
    apply(c,[raw()]);assert not w.dataset(c)['coverage'][0]['complete']


def test_sync_partial_error_atomic(tmp_path,source,monkeypatch):
    db=tmp_path/'fleet.sqlite'
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row;w.initialize(c,source)
    monkeypatch.setattr(t,'credentials',lambda _:dict(api_key='not-a-real-key',api_user_id=1))
    def fail(_,params):
        if params['FromOrderDate']=='2026-08-02':raise ValueError('test failure')
        return [raw()]
    monkeypatch.setattr(t,'get_orders',fail)
    with pytest.raises(ValueError):t.sync(tmp_path,db,'2026-08-01','2026-08-02')
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row
        assert w.dataset(c)['trips'][0]['revenue']==900
        assert t.status(c)['status']=='error'


def test_sync_range_disagreement_rejects(tmp_path,source,monkeypatch):
    db=tmp_path/'fleet.sqlite'
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row;w.initialize(c,source)
    monkeypatch.setattr(t,'credentials',lambda _: {})
    replies=iter([[raw()],[]]);monkeypatch.setattr(t,'get_orders',lambda *_:next(replies))
    with pytest.raises(ValueError,match='различаются'):t.sync(tmp_path,db,'2026-08-01','2026-08-01')
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row;assert w.dataset(c)['trips'][0]['revenue']==900


def test_signed_readonly_request_and_redacted_error(monkeypatch):
    import hashlib
    config=dict(api_key='not-a-real-key',api_user_id=5)
    def post(url,**kw):
        p=kw['data'];assert url==t.URL and p['method']=='GetOrders' and not kw['allow_redirects']
        assert json.loads(p['data'])['api_user_id']==5
        assert p['signature']==hashlib.md5('###'.join([config['api_key'],p['data'],p['method'],p['random'],config['api_key']]).encode()).hexdigest()
        class Response:
            status_code=200
            def json(self):return dict(error_code=1,error_text=config['api_key'])
        return Response()
    monkeypatch.setattr(t.requests,'post',post)
    with pytest.raises(ValueError) as e:t.get_orders(config,{})
    assert config['api_key'] not in str(e.value)


def test_iso_week_group_cross_year():
    rows=[dict(t.normalize(raw()),date='2027-01-01'),dict(t.normalize(raw('2')),date='2026-12-31')]
    r=analytics.report(dict(trips=rows,plans=[],satellite=[]),{'group':'week'})
    assert len(r['rows'])==1 and r['rows'][0]['name']=='2026-W53' and r['rows'][0]['records']==2


def test_null_comparison_even_with_confirmed_period(c):
    apply(c,[raw()])
    for source in ('trips','plans'):w.save_extra(c,'coverage',dict(start='2026-08-01',end='2026-08-31',source=source,complete=True),ADMIN)
    r=reports.comparison(w.dataset(c),dict(from_='ignored',**{'from':'2026-08-01','to':'2026-08-31'}))['rows'][0]
    assert r['fact_km'] is None and r['delta_km'] is None


def test_cancel_preserves_override_for_reactivation(c):
    row=w.dataset(c)['trips'][0]
    w.edit_record(c,row['record_id'],dict(category='Сервис',revision=row['revision']),ADMIN)
    apply(c,[dict(raw(),Status='Отмена')]);assert w.dataset(c)['trips'][0]['category_override']=='Сервис'
    apply(c,[raw()]);assert w.dataset(c)['trips'][0]['category']=='Сервис'


def test_transport_binds_only_provider_and_keeps_tls(tmp_path,monkeypatch):
    (tmp_path/'transtrade-network.json').write_text('{"interface":"en0"}')
    monkeypatch.setattr(t.sys,'platform','darwin')
    monkeypatch.setattr(t.socket,'if_nametoindex',lambda name: 7 if name=='en0' else 0)
    with t.transport(tmp_path) as http:
        assert http.verify is True
        adapter=http.get_adapter(t.URL)
        assert (t.socket.IPPROTO_IP,25,7) in adapter.poolmanager.connection_pool_kw['socket_options']
        assert http.get_adapter('https://example.com/') is not adapter


def test_transport_missing_interface_fails(tmp_path,monkeypatch):
    (tmp_path/'transtrade-network.json').write_text('{"interface":"missing"}')
    monkeypatch.setattr(t.sys,'platform','darwin')
    def fail(_):raise OSError('missing')
    monkeypatch.setattr(t.socket,'if_nametoindex',fail)
    with pytest.raises(ValueError,match='недоступен'):t.transport(tmp_path)


@pytest.mark.parametrize('answer',['found','empty','wrong','error'])
def test_sync_recovers_known_list_omissions_atomically(tmp_path,source,monkeypatch,answer):
    db=tmp_path/'fleet.sqlite'
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row;w.initialize(c,source)
        old=w.dataset(c)['trips'][0]
        w.edit_record(c,old['record_id'],{'revision':old['revision'],'category':'Сервис'},ADMIN)
    monkeypatch.setattr(t,'credentials',lambda _: {})
    calls=[]
    def fetch(_,params):
        calls.append(params)
        if 'OrderId' not in params:return []
        assert params=={'OrderId':1}
        if answer=='error':raise ValueError('test error')
        return [] if answer=='empty' else [raw('2' if answer=='wrong' else '1')]
    monkeypatch.setattr(t,'get_orders',fetch)
    if answer in ('wrong','error'):
        with pytest.raises(ValueError):t.sync(tmp_path,db,'2026-08-01','2026-08-01')
    else:
        result=t.sync(tmp_path,db,'2026-08-01','2026-08-01')
        assert result['recovered_by_id']==(answer=='found')
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row;trips=w.dataset(c)['trips'];assert len(trips)==1
        r=trips[0];assert r['record_id']==old['record_id'] and r['category']=='Сервис'
        if answer=='found':
            assert r['api_list_omitted'] and not r.get('api_missing') and r['legacy_snapshot']
        elif answer=='empty':assert r['api_missing'] and r['revenue']==900
        else:assert not r.get('api_missing') and r['revenue']==900
    if answer=='found':
        result=t.sync(tmp_path,db,'2026-08-01','2026-08-01')
        assert result['unchanged']==1 and result['created']==result['updated']==0


def test_recovered_date_move_invalidates_both_periods(c):
    for month in ('08','09'):
        w.save_extra(c,'coverage',dict(start=f'2026-{month}-01',end=f'2026-{month}-28',source='trips',complete=True),ADMIN)
    moved=dict(raw(),BeginDateTime='2026-09-01 08:00:00',EndDateTime='2026-09-01 12:00:00')
    result=t.apply(c,[],'2026-08-01','2026-08-31',[moved])
    assert result['moved_out_of_period']==1 and result['received']==0 and result['missing']==0
    d=w.dataset(c);assert d['trips'][0]['date']=='2026-09-01'
    assert all(not x['complete'] for x in d['coverage'])
    assert d['trips'][0]['legacy_snapshot']['date']=='2026-08-01'


def test_list_return_clears_omission_and_unknown_recovery_rejected(c):
    with pytest.raises(ValueError):t.apply(c,[],'2026-08-01','2026-08-31',[raw('99')])
    t.apply(c,[],'2026-08-01','2026-08-31',[raw()])
    assert w.dataset(c)['trips'][0]['api_list_omitted']
    apply(c,[raw()]);assert not w.dataset(c)['trips'][0].get('api_list_omitted')
