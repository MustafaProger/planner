import json
import sqlite3
from app import demo_data, workspace


def test_demo_seed_is_fictional_complete_and_idempotent(tmp_path):
    source=tmp_path/'login.sqlite'
    with sqlite3.connect(source) as c:
        c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT,password TEXT,role TEXT,vehicles TEXT)')
        c.execute("INSERT INTO users VALUES(1,'demo-login','unused-hash','admin','[]')")
    target=tmp_path/'demo'
    summary=demo_data.seed(target,source)
    assert summary['vehicles']==10 and summary['drivers']==12
    with sqlite3.connect(target/'fleet.sqlite') as c:
        c.row_factory=sqlite3.Row
        d=workspace.dataset(c)
        assert len(d['trips'])==summary['trips']+summary['charges']
        assert len(d['plans'])==240
        assert {r['origin'] for r in d['trips']}=={'demo'}
        assert all(r['source']==demo_data.SOURCE for r in d['trips'])
        assert any(r['date']=='2026-11-14' and r['end'].startswith('2026-11-15') for r in d['trips'])
        c.execute("UPDATE users SET name='local-edit' WHERE id=1")
    assert demo_data.seed(target,source)==summary
    with sqlite3.connect(target/'fleet.sqlite') as c:
        assert c.execute('SELECT name FROM users WHERE id=1').fetchone()[0]=='local-edit'
    fixture=demo_data.facts(target)
    assert fixture['period']==['2026-11-01','2026-11-30']
    assert len(fixture['fuel'])>400
    assert all(r['demo'] for r in fixture['satellite']+fixture['fuel'])
    assert any(not r['vehicle'] for r in fixture['fuel'])


def test_demo_requires_both_local_and_explicit_demo_flags(monkeypatch):
    monkeypatch.setenv('FLEET_DEMO','1');monkeypatch.delenv('FLEET_LOCAL_PREVIEW',raising=False)
    assert not demo_data.enabled()
    monkeypatch.setenv('FLEET_LOCAL_PREVIEW','1')
    assert demo_data.enabled()
