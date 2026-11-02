import json
import pytest
from app.importer import load_excel,resolve_sources
from app.analytics import report
from excel_fixture import books


@pytest.fixture
def unconfigured(monkeypatch,tmp_path):
    for name in ('FLEET_EXCEL_DIR','FLEET_STATISTICS_XLSX','FLEET_PLANNER_XLSX'):monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('FLEET_EXCEL_CONFIG',str(tmp_path/'missing.json'))


def test_missing_sources_explains_configuration(unconfigured):
    assert resolve_sources(required=False)==(None,None)
    with pytest.raises(ValueError,match='FLEET_EXCEL_DIR'):load_excel()


def test_explicit_books_independent_of_cwd_and_broken_config(unconfigured,tmp_path,monkeypatch):
    paths=books(tmp_path/'books')
    bad=tmp_path/'invalid.json';bad.write_text('{')
    monkeypatch.setenv('FLEET_EXCEL_CONFIG',str(bad));monkeypatch.chdir(tmp_path)
    data=load_excel(*paths)
    assert len(data['trips'])==4
    assert sum(r['revenue'] for r in data['trips'])==3200
    result=report(data,{})['totals']
    assert result['trips']==2 and result['days']==1
    assert result['km']==300 and result['hours']==31
    assert data['trips'][1]['hours']==27
    assert data['statuses'][0]['kind']=='vehicle'


def test_local_config_relative_paths_and_env_priority(unconfigured,tmp_path,monkeypatch):
    paths=books(tmp_path/'books');config=tmp_path/'sources.json'
    config.write_text(json.dumps({'statistics':'books/statistics.xlsx','planner':'books/planner.xlsx'}))
    monkeypatch.setenv('FLEET_EXCEL_CONFIG',str(config));monkeypatch.chdir(tmp_path.parent)
    assert resolve_sources()==paths
    alternative=books(tmp_path/'alternative')
    monkeypatch.setenv('FLEET_STATISTICS_XLSX',str(alternative[0]))
    monkeypatch.setenv('FLEET_PLANNER_XLSX',str(alternative[1]))
    assert resolve_sources()==alternative
    assert len(load_excel()['trips'])==4


def test_import_pair_validated_before_open(unconfigured,tmp_path):
    paths=books(tmp_path)
    paths[1].unlink()
    with pytest.raises(ValueError,match='обе книги'):load_excel(*paths)


def test_environment_does_not_read_unused_broken_local_config(unconfigured,tmp_path,monkeypatch):
    from app.importer import STATISTICS_NAME,PLANNER_NAME
    paths=books(tmp_path/'books');bad=tmp_path/'invalid.json';bad.write_text('{')
    monkeypatch.setenv('FLEET_EXCEL_CONFIG',str(bad))
    monkeypatch.setenv('FLEET_STATISTICS_XLSX',str(paths[0]));monkeypatch.setenv('FLEET_PLANNER_XLSX',str(paths[1]))
    assert resolve_sources()==paths
    monkeypatch.delenv('FLEET_STATISTICS_XLSX');monkeypatch.delenv('FLEET_PLANNER_XLSX')
    target=(paths[0].with_name(STATISTICS_NAME),paths[1].with_name(PLANNER_NAME))
    paths[0].rename(target[0]);paths[1].rename(target[1])
    monkeypatch.setenv('FLEET_EXCEL_DIR',str(target[0].parent))
    assert resolve_sources()==target
