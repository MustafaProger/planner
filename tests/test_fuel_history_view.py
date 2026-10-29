import json

import pytest

from app import fuel_history


OLD='2026-09-01T10:00:00+00:00'
NEW='2026-10-29T07:00:00+00:00'


def save(path,value):
    path.write_text(json.dumps(value))


@pytest.mark.parametrize('provider,date_field', [('neftm','dateRec'),('rosneft','Date')])
def test_old_period_survives_new_month_snapshot_and_reports_its_own_freshness(tmp_path,provider,date_field):
    old={date_field:'2026-08-31T23:59:59+03:00','id':'august'}
    new={date_field:'2026-10-29T10:00:00+03:00','id':'october'}
    history=dict(provider=provider,rows=[old,new],cards=[{'Num':'001'}],synced_at=NEW,
                 periods=[{'from':'2026-08-01','to':'2026-08-31','synced_at':OLD},
                          {'from':'2026-10-01','to':'2026-10-29','synced_at':NEW}])
    save(tmp_path/(provider+'-history.json'),history)
    save(tmp_path/(provider+'-transactions.json'),dict(provider=provider,rows=[new],synced_at=NEW,
                                                    **{'from':'2026-10-01','to':'2026-10-29'}))
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    result=fuel_history.snapshot_for_period(tmp_path,provider,'2026-08-01','2026-08-31')
    assert result['rows']==[old]
    assert result['complete'] is True and result['synced_at']==OLD
    assert result['cards']==[{'Num':'001'}] and result['cards_synced_at']==NEW
    assert len(result['periods'])==2
    assert before=={p.name:p.read_bytes() for p in tmp_path.iterdir()}


def test_snapshot_fallback_and_successful_empty_days(tmp_path):
    save(tmp_path/'neftm-transactions.json',{'provider':'neftm','from':'2026-08-01','to':'2026-08-31',
                                          'synced_at':OLD,'rows':[]})
    result=fuel_history.snapshot_for_period(tmp_path,'neftm','2026-08-15','2026-08-16')
    assert result['complete'] is True and result['rows']==[] and result['synced_at']==OLD
    assert result['periods']==[{'from':'2026-08-01','to':'2026-08-31','synced_at':OLD}]


def test_union_coverage_and_conservative_freshness_for_partially_refreshed_month(tmp_path):
    save(tmp_path/'rosneft-history.json',{'rows':[], 'synced_at':NEW,'periods':[
        {'from':'2026-08-01','to':'2026-08-15','synced_at':OLD},
        {'from':'2026-08-16','to':'2026-08-31','synced_at':OLD},
        {'from':'2026-08-01','to':'2026-08-05','synced_at':NEW}]})
    full=fuel_history.snapshot_for_period(tmp_path,'rosneft','2026-08-01','2026-08-31')
    partial=fuel_history.snapshot_for_period(tmp_path,'rosneft','2026-08-01','2026-08-05')
    assert full['complete'] is True and full['synced_at']==OLD
    assert partial['complete'] is True and partial['synced_at']==NEW


def test_uncovered_day_and_unknown_timestamps_do_not_borrow_latest_snapshot_time(tmp_path):
    history={'synced_at':NEW,'rows':[{'Date':'2026-08-01T10:00:00'}],
             'periods':[{'from':'2026-08-01','to':'2026-08-01','synced_at':OLD},
                        {'from':'2026-08-03','to':'2026-08-03','synced_at':NEW}]}
    save(tmp_path/'rosneft-history.json',history)
    result=fuel_history.snapshot_for_period(tmp_path,'rosneft','2026-08-01','2026-08-03')
    assert not result['complete'] and result['synced_at'] is None and len(result['rows'])==1
    history['periods']=[{'from':'2026-08-01','to':'2026-08-31'}]
    save(tmp_path/'rosneft-history.json',history)
    result=fuel_history.snapshot_for_period(tmp_path,'rosneft','2026-08-01','2026-08-31')
    assert result['complete'] is True and result['synced_at'] is None


@pytest.mark.parametrize('provider,start,end',[
    ('../neftm','2026-08-01','2026-08-31'),('other','2026-08-01','2026-08-31'),
    ('neftm',None,None),('rosneft','20260801','2026-08-31'),
    ('rosneft','2026-08-02','2026-08-01'),('neftm','2026-08-01','2026-09-01'),
    ('rosneft','2026-08-01T00:00:00','2026-08-31'),('neftm','2026-02-30','2026-03-01')])
def test_invalid_provider_or_period_rejected(tmp_path,provider,start,end):
    with pytest.raises(ValueError):
        fuel_history.snapshot_for_period(tmp_path,provider,start,end)
    assert list(tmp_path.iterdir())==[]


def test_empty_cache_is_not_zero_coverage(tmp_path):
    result=fuel_history.snapshot_for_period(tmp_path,'neftm','2026-08-01','2026-08-31')
    assert result['rows']==[] and result['periods']==[] and result['cards']==[]
    assert result['complete'] is False and result['synced_at'] is None


def test_route_is_admin_only_validates_period_and_reads_without_api(tmp_path,monkeypatch):
    # Isolate even when this module runs alone; importing server never uses live data.
    monkeypatch.setenv('FLEET_DATA',str(tmp_path))
    from app import server,neftm,rosneft
    monkeypatch.setattr(server,'DATA',tmp_path)
    for module in (neftm,rosneft):
        monkeypatch.setattr(module,'sync',lambda *args:pytest.fail('GET must not call a provider'))
    client=server.app.test_client()
    monkeypatch.setattr(server,'user',lambda:None)
    url='/api/fuel-history/neftm?from=2026-08-01&to=2026-08-31'
    assert client.get(url).status_code==401
    for role in ('viewer','logist'):
        monkeypatch.setattr(server,'user',lambda role=role:{'role':role})
        assert client.get(url).status_code==403
    monkeypatch.setattr(server,'user',lambda:{'role':'admin'})
    response=client.get(url)
    assert response.status_code==200 and response.json['provider']=='neftm'
    assert response.json['from']=='2026-08-01' and response.json['complete'] is False
    assert client.get('/api/fuel-history/unknown?from=2026-08-01&to=2026-08-31').status_code==400
    assert client.get('/api/fuel-history/neftm').status_code==400
