"""Source records explain the exact report scope, including mixed telemetry."""
import copy
import pytest
from app import reports
from app.monitoring_history import merge_satellite


def record(ident, **changes):
    return dict(dict(id=ident, record_id=ident, revision=1, date='2026-08-01',
                     vehicle='Авто А', vehicle_id='v1', driver='Водитель · Один', driver_id='d1',
                     route='Маршрут А', state='scheduled', category='Рейс', revenue=1000,
                     payout=400, km=100, hours=4, source='synthetic'), **changes)


def sample():
    return dict(plans=[record('p1'), record('p2',date='2026-08-02',revenue=2000),
                       record('p3',vehicle='Авто Б',vehicle_id='v2',driver='Другой',driver_id='d2',route='Маршрут Б'),
                       record('excluded',state='review'), record('cancelled-plan',state='cancelled'),
                       record('outside',date='2026-09-01')],
                trips=[record('t1',revenue=900,km=None), record('t2',date='2026-08-02',revenue=800),
                       record('charge',category='Доплата',revenue=250,km=9000,hours=900),
                       record('cancelled-trip',cancelled=True,revenue=999999),
                       record('other-car',vehicle='Авто Б',vehicle_id='v2',driver='Другой',driver_id='d2'),
                       record('outside-trip',date='2026-09-01')],
                satellite=[], coverage=[], directories={'drivers':[dict(id='d1',company='Компания А'),dict(id='d2',company='Компания Б')]})


PERIOD={'from':'2026-08-01','to':'2026-08-31'}


@pytest.mark.parametrize('group',['vehicle','driver','route','company','date','month','quarter','year'])
def test_plan_detail_selection_matches_every_report_group(group):
    d=sample(); before=copy.deepcopy(d); q=dict(PERIOD,mode='plans',group=group)
    result=reports.plan_rows(d,q)
    seen=[]
    for row in result['rows']:
        detail=reports.report_details(d,dict(q,row=row['name']))
        assert detail['summary']==row
        assert sum(x['revenue'] for x in detail['plans'])==row['revenue']
        assert len(detail['plans'])==row['trips']
        assert all(reports.eligible(x) for x in detail['plans'])
        assert not detail['trips'] and not detail['excluded_trips']
        seen.extend(x['id'] for x in detail['plans'])
    assert sorted(seen)==['p1','p2','p3']
    assert d==before


def test_plan_placeholder_and_filtered_period_preserve_original_records():
    d=sample(); d['plans']=[record('service',vehicle='Нет марш'),record('unknown',vehicle='')]
    q=dict(PERIOD,mode='plans',group='vehicle')
    first=reports.report_details(d,dict(q,row='Не назначен'))
    assert first['plans'][0]['vehicle']=='Нет марш'
    assert first['summary']['name']=='Не назначен'
    assert reports.report_details(d,dict(q,row='Не указано'))['plans'][0]['id']=='unknown'
    d=sample(); q=dict(PERIOD,mode='plans',group='company',vehicle='Авто А',driver='Водитель · Один',to='2026-08-01')
    detail=reports.report_details(d,dict(q,row='Компания А'))
    assert [r['id'] for r in detail['plans']]==['p1']
    assert {r['record']['id'] for r in detail['excluded_plans']}=={'excluded','cancelled-plan'}
    assert all(r['reason'] for r in detail['excluded_plans'])
    assert detail['scope']['to']=='2026-08-01'


@pytest.mark.parametrize('group',['vehicle','driver','pair'])
def test_comparison_details_keep_all_scope_completeness_and_separate_charges(group,monkeypatch):
    d=sample(); d['plans']=[r for r in d['plans'] if r['id']!='excluded']
    d['plans'].append(record('unresolved-other',vehicle='Авто Б',driver='Другой',state='review'))
    monkeypatch.setattr(reports,'coverage',lambda *args:True)
    q=dict(PERIOD,mode='comparison',group=group)
    name={'vehicle':'Авто А','driver':'Водитель · Один','pair':'Авто А · Водитель · Один'}[group]
    detail=reports.report_details(d,dict(q,row=name))
    expected=next(x for x in reports.comparison(d,q)['rows'] if x['name']==name)
    assert detail['summary']==expected
    assert not detail['plan_complete'] and detail['fact_complete']
    assert detail['summary']['delta_revenue'] is None  # Another group still invalidates the original period.
    assert {r['id'] for r in detail['plans']}=={'p1','p2'}
    assert {r['id'] for r in detail['trips']}=={'t1','t2'}
    assert detail['summary']['fact_revenue']==1700
    assert detail['summary']['fact_km'] is None
    assert [r['record']['id'] for r in detail['excluded_trips']]==['charge']
    assert [r['record']['id'] for r in detail['excluded_plans']]==['cancelled-plan']


def test_detail_empty_side_uses_same_explicit_zero_and_group_fallback(monkeypatch):
    d=sample(); d['plans']=[]; monkeypatch.setattr(reports,'coverage',lambda *args:True)
    detail=reports.report_details(d,dict(PERIOD,mode='comparison',group='route',row='Авто А'))
    assert detail['group']=='vehicle' and detail['plans']==[]
    assert detail['summary']['plan_revenue']==0 and detail['summary']['delta_revenue']==1700
    monkeypatch.setattr(reports,'coverage',lambda *args:False)
    detail=reports.report_details(d,dict(PERIOD,mode='comparison',row='Авто А'))
    assert detail['summary']['plan_revenue'] is None and detail['summary']['delta_revenue'] is None
    assert reports.report_details(d,dict(PERIOD,mode='comparison',row='removed')) is None


def telemetry_sample(api_km=334):
    d=sample(); raw=[dict(vehicle='Авто А',date='2026-08-01',start='2026-08-01T00:00:00',end='2026-08-02T00:00:00',
                          km=310,hours=24,engine_hours=6,movement_hours=3,stop_hours=21,source='Excel',private_blob='not an exposed field')]
    api=[dict(vehicle='Авто А',date='2026-08-01',km=api_km,engine_hours=5,fuel_liters=25,
              mileage_status='ok',fuel_status='ok',synced_at='2026-08-02T02:00:00+03:00')]
    d['satellite_raw']=raw; d['satellite']=merge_satellite(raw,api)
    d['satellite'].append(dict(vehicle='Авто Б',date='2026-08-01',km=999,hours=1))
    return d


def test_reconciliation_details_explain_metric_specific_replacement_without_double_count():
    d=telemetry_sample(); before=copy.deepcopy(d)
    result=reports.reconcile_details(d,{'vehicle':'Авто А','date':'2026-08-01'})
    assert result['summary']==next(r for r in reports.reconcile(d,PERIOD) if r['vehicle']=='Авто А' and r['date']=='2026-08-01')
    assert result['summary']['sat_km']==334 and result['summary']['sat_hours']==24
    assert result['summary']['tt_km'] is None and result['summary']['delta_km'] is None
    assert [r['id'] for r in result['trips']]==['t1']
    assert [r['record']['id'] for r in result['other_trips']]==['charge']
    assert result['metric_usage']['km']==dict(value=334,source='ГЛОНАССсофт API',excel_role='replaced_by_api')
    assert result['metric_usage']['hours']==dict(value=24,source='Excel',excel_role='used')
    assert result['satellite_raw'][0]['km']==310 and result['satellite'][0]['km']==334
    assert result['satellite_raw'][0]['metric_usage']['km']=='replaced_by_api'
    assert 'private_blob' not in result['satellite_raw'][0]
    assert d==before


def test_reconciliation_missing_api_value_keeps_excel_and_satellite_only_days():
    d=telemetry_sample(api_km=None)
    result=reports.reconcile_details(d,{'vehicle':'Авто А','date':'2026-08-01'})
    assert result['metric_usage']['km']==dict(value=310,source='Excel',excel_role='used')
    d['trips']=[]
    result=reports.reconcile_details(d,{'vehicle':'Авто А','date':'2026-08-01'})
    assert result['trips']==[] and result['summary']['state']=='Нет заявок'
    assert result['summary']['sat_km']==310
    assert reports.reconcile_details(d,{'vehicle':'Авто А','date':'2026-08-02'}) is None


def test_reconciliation_without_monitoring_uses_original_excel_intervals():
    d=sample(); d['satellite']=[dict(vehicle='Авто А',date='2026-08-01',km=0,hours=2,source='Excel')]
    result=reports.reconcile_details(d,{'vehicle':'Авто А','date':'2026-08-01'})
    assert result['metric_usage']['km']==dict(value=0,source='Excel',excel_role='used')
    assert result['satellite'][0]['km']==0 and result['satellite_raw'][0]['km']==0
    d['satellite']=[]
    result=reports.reconcile_details(d,{'vehicle':'Авто А','date':'2026-08-01'})
    assert result['satellite']==[] and result['satellite_raw']==[]
    assert result['metric_usage']['km']['value'] is None


@pytest.mark.parametrize('q',[{'mode':'economics','row':'A'},{'mode':'plans'},
                              {'mode':'plans','row':'A','from':'broken'},
                              {'mode':'plans','row':'A','from':'20260801'},
                              {'mode':'plans','row':'A','from':'2026-08-02','to':'2026-08-01'}])
def test_invalid_detail_scope_is_rejected(q):
    with pytest.raises(ValueError):reports.report_details(sample(),q)


def test_http_detail_auth_validation_and_no_writes(monkeypatch,tmp_path):
    monkeypatch.setenv('FLEET_DATA',str(tmp_path));monkeypatch.setenv('FLEET_SCHEDULER','disabled')
    from app import server
    d=telemetry_sample(); before=copy.deepcopy(d)
    monkeypatch.setattr(server,'dataset',lambda:d)
    monkeypatch.setattr(server,'user',lambda:None)
    client=server.app.test_client()
    paths=['/api/workspace/report/details?mode=plans&row=Авто А','/api/reconcile/details?vehicle=Авто А&date=2026-08-01']
    for url in paths:assert client.get(url).status_code==401
    for role in ('admin','logist','viewer'):
        monkeypatch.setattr(server,'user',lambda:dict(id=99,role=role,vehicles=[]))
        for url in paths:
            assert client.get(url).status_code==200
            assert client.post(url,json={}).status_code==405
    assert client.get('/api/workspace/report/details?mode=economics&row=A').status_code==400
    assert client.get('/api/workspace/report/details?mode=plans&row=gone').status_code==404
    assert client.get('/api/reconcile/details?vehicle=Авто А&date=invalid').status_code==400
    assert client.get('/api/reconcile/details?vehicle=Авто А&date=2027-01-01').status_code==404
    assert d==before
