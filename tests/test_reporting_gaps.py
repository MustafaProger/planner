import copy
import pytest
from app.analytics import report, aggregate, prepare_rows
from app import reports


def trip(ident, **values):
    return dict(dict(id=ident,record_id=ident,date='2026-08-01',vehicle='Авто 1',vehicle_id='v1',driver='Водитель 1',driver_id='d1',client='Клиент',carrier='Исполнитель',type='Грузовой',category='Рейс',revenue=1000,payout=400,km=100,hours=4),**values)


def dataset(rows):
    return dict(trips=rows,plans=[],satellite=[],directories={
        'vehicles':[dict(id='v1',name='Авто 1',brand='Газель',company='Парк А',resource_type='vehicle'),dict(id='v2',name='Авто 2',brand='Газель',company='Парк Б',resource_type='partner')],
        'drivers':[dict(id='d1',name='Водитель 1',company='Водители А'),dict(id='d2',name='Водитель 2',company='Водители Б')]})


def test_groups_do_not_multiply_facts_or_guess_company():
    d=dataset([trip('1'),trip('2',vehicle='Авто 2',vehicle_id='v2',revenue=2000),trip('3',vehicle='Неизвестная',vehicle_id='missing',revenue=300)])
    before=copy.deepcopy(d)
    for group in ('vehicle_brand','vehicle_company','driver_company','resource_type','carrier'):
        r=report(d,{'group':group})
        assert sum(x['revenue'] for x in r['rows'])==r['totals']['revenue']==3300
        assert len(r['trips'])==3
        assert all('Текущий справочник' in t['attribute_basis'] for t in r['trips'])
    brands={r['name']:r for r in report(d,{'group':'vehicle_brand'})['rows']}
    assert brands['Газель']['revenue']==3000 and brands['Не указано']['revenue']==300
    assert d==before
    with pytest.raises(ValueError,match='Неизвестная группировка'):report(d,{'group':'company'})


def test_filter_details_and_export_rows_share_one_selection():
    d=dataset([trip('1'),trip('2',vehicle='Авто 2',vehicle_id='v2',driver='Водитель 2',driver_id='d2'),trip('3',vehicle_id='missing')])
    for key,value,ids in [('vehicle_brand','Газель',['1','2']),('vehicle_company','Парк Б',['2']),('driver_company','Водители Б',['2']),('resource_type','partner',['2']),('vehicle_brand','Не указано',['3'])]:
        r=report(d,{key:value,'group':'driver'})
        assert [t['id'] for t in r['trips']]==ids
        assert sum(t['revenue'] for t in r['trips'])==r['totals']['revenue']==sum(t['revenue'] for t in r['rows'])
    # Stable ID takes precedence over stale visible name; merged directory references follow once.
    d['directories']['vehicles'][0]['name']='Переименованная'
    d['directories']['vehicles'].append(dict(id='old',name='Старая',merged_into='v1'))
    d['trips'][0]['vehicle_id']='old'
    assert prepare_rows(d,d['trips'])[0]['vehicle_brand']=='Газель'


def test_means_distinguish_records_trips_and_total_money():
    d=dataset([trip('1'),trip('2',revenue=2000,payout=800,km=200,hours=8),trip('3',category='Доплата',revenue=300,payout=100,km=999,hours=999),trip('4',category='Удержание',revenue=-100,payout=-100),trip('5',revenue=900000,cancelled=True)])
    t=report(d,{})['totals']
    assert (t['revenue'],t['records'],t['trips'],t['days'])==(3200,4,2,1)
    assert (t['average_record_revenue'],t['average_trip_revenue'],t['revenue_per_trip'])==(800,1500,1600)
    assert (t['average_record_payout'],t['average_trip_payout'])==(300,600)
    assert (t['average_km'],t['average_hours'])==(150,6)
    assert t['average_counts']==dict(records=4,trips=2,known_revenue=4,known_payout=4,known_km=2)


def test_total_is_weighted_by_raw_records_and_missing_is_not_zero():
    d=dataset([trip('1'),trip('2',revenue=2000),trip('3',vehicle_id='v2',vehicle='Авто 2',revenue=9000)])
    r=report(d,{'group':'vehicle'})
    assert r['totals']['average_trip_revenue']==4000
    assert sum(x['average_trip_revenue'] for x in r['rows'])/2!=4000
    d['trips'][0].update(km=None,revenue=None)
    t=report(d,{})['totals']
    assert t['average_km'] is None and t['average_record_revenue'] is None and t['average_trip_revenue'] is None
    assert t['average_record_payout']==400
    t=aggregate([trip('1',category='Удержание',revenue=-100)],'vehicle')[0]
    assert t['average_record_revenue']==-100 and t['average_trip_revenue'] is None and t['average_hours'] is None
    t=aggregate([trip('1',revenue=0,km=0,hours=0)],'vehicle')[0]
    assert t['average_trip_revenue']==0 and t['average_km']==0 and t['rub_km'] is None


def test_driver_company_filter_does_not_attribute_vehicle_telemetry():
    d=dataset([trip('1')]);d['satellite']=[dict(vehicle='Авто 1',date='2026-08-01',km=1000)]
    assert 'sat_km' not in report(d,{'driver_company':'Водители А'})['rows'][0]


def test_six_comparison_deltas_and_metric_specific_reasons(monkeypatch):
    monkeypatch.setattr(reports,'coverage',lambda *args:True)
    d=dataset([trip('1',revenue=1200,payout=300,km=None,hours=5)])
    d['plans']=[trip('p',revenue=1000,payout=400,km=100,hours=4,state='scheduled')]
    row=reports.comparison(d,{})['rows'][0]
    assert [row['delta_'+k] for k in ('trips','days','revenue','payout','km','hours')]==[0,0,200,-100,None,1]
    assert row['delta_reasons']['km']=='Нет полного показателя факта'
    assert row['delta_reasons']['revenue']==''
    monkeypatch.setattr(reports,'coverage',lambda *args:False)
    row=reports.comparison(d,{})['rows'][0]
    assert row['fact_revenue']==1200 and row['delta_revenue'] is None
    assert 'Полнота плана' in row['delta_reasons']['revenue']


def test_review_assignment_remains_an_actionable_quality_item():
    d=dataset([]);d['plans']=[trip('p',state='review',route='Маршрут')];d['directories']['drivers']=[]
    result=reports.quality(d,{})
    assert len(result['rows'])==1 and result['rows'][0]['kind']=='plans'
    assert result['rows'][0]['record']['state']=='review'
    assert 'Назначение требует проверки' in result['rows'][0]['issue']
