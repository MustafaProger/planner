"""Acceptance of the privately supplied books, separate from portable API tests.

Set FLEET_EXCEL_DIR or the two individual paths; no books are committed.
"""
import pytest
from app.importer import load_excel,resolve_sources
from app.analytics import report

@pytest.fixture(scope='module')
def data():
    paths=resolve_sources(required=False)
    if not all(paths):pytest.skip('Private source books not configured; portable importer/API tests still run')
    return load_excel(*paths)

def test_raw_excel_totals(data):
    assert len(data['trips'])==996
    assert sum(r['revenue'] for r in data['trips'])==pytest.approx(13724319.06)
    assert sum(r['payout'] for r in data['trips'])==pytest.approx(6930671.46)
    assert sum(r['km'] for r in data['trips'])==99197
    assert sum(r['hours'] for r in data['trips'])==pytest.approx(9330)


def test_satellite_matches_pivot(data):
    assert sum(r['km'] for r in data['satellite'])==pytest.approx(54294.4)
    assert sum(r['hours'] for r in data['satellite'])==pytest.approx((154*24+8)+26/60+7/3600)


def test_plan_routes_and_totals(data):
    assert len(data['plans'])==1436 and len(data['routes'])==114
    assert sum(r['revenue'] for r in data['plans'])==pytest.approx(20637711.5)
    assert sum(r['payout'] for r in data['plans'])==pytest.approx(10318935)
    assert {r['date'][:7] for r in data['plans']}=={'2026-07','2026-09'}


def test_non_trip_charges_do_not_inflate_work(data):
    t=report(data,{})['totals']
    assert t['trips']==815 and t['km']==94699
    assert t['hours']==pytest.approx(6208.2666666667)
    assert t['average_hours']==pytest.approx(t['hours']/815)
    assert t['revenue']==pytest.approx(13724319.06)


def test_filter_and_actual_days(data):
    t=report(data,{'vehicle':'Т711РМ797','from':'2026-08-01','to':'2026-08-31'})['totals']
    assert t['revenue']==pytest.approx(471437.88,abs=0.001)
    assert t['trips']==40
    assert not report(data,{'from':'2026-09-01','to':'2026-09-30'})['trips']


def test_status_dedup(data):
    keys=[(r['date'],r['kind'],r['entity'],r['reason']) for r in data['statuses']]
    assert len(keys)==len(set(keys))==181
    assert any('; Блокнот!' in r['source'] for r in data['statuses'])


def test_carrier_matches_cached_excel_pivot(data):
    t=report(data,{'carrier':'ООО "ЧАРТЕР"'})['totals']
    assert t['revenue']==pytest.approx(5643144.06,abs=0.001)
    assert t['payout']==pytest.approx(1680936.81,abs=0.001) # matches Статистика!Q8, includes unassigned entries
    assigned=sum(r['payout'] for r in data['trips'] if r['carrier']=='ООО \"ЧАРТЕР\"' and r['vehicle'])
    assert assigned==pytest.approx(1613936.81,abs=0.001) # matches Статистика!K8
