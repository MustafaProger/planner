"""G02/G06 business-content attestations and stale deletes on isolated data."""
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import workspace as w, reports, transtrade as tt
from app.coverage import preview
from tests.test_workspace import source, c, ADMIN, plan, confirmation
from tests.test_transtrade import raw


def confirm(c,source='plans',start='2026-07-01',end='2026-09-30'):
    return w.save_extra(c,'coverage',confirmation(c,dict(source=source,start=start,end=end,complete=True)),ADMIN)


def state(c,ident):
    return next(r for r in w.dataset(c)['coverage'] if r['id']==ident)


def test_legacy_attestation_requires_review(c):
    c.execute('insert into coverage(id,body) values(?,?)',('legacy',w.dump(dict(source='plans',start='2026-07-01',end='2026-07-31',complete=True))))
    r=state(c,'legacy')
    assert r['checked_complete'] and r['stale'] and not r['complete']
    assert not reports.coverage(w.dataset(c),{'from':'2026-07-01','to':'2026-07-31'},'plans')


def test_preview_stale_or_missing_is_rejected(c):
    b=confirmation(c,dict(source='plans',start='2026-09-01',end='2026-09-30',complete=True))
    w.create_records(c,'plans',plan(c),ADMIN)
    for stale in (b,{k:v for k,v in b.items() if k not in ('checked_fingerprint','fingerprint_algorithm')}):
        with pytest.raises(w.ConflictError):w.save_extra(c,'coverage',stale,ADMIN)
    assert not w.dataset(c)['coverage']


def test_create_edit_delete_and_outside_period(c):
    july=confirm(c,end='2026-07-31');september=confirm(c,start='2026-09-01')
    w.create_records(c,'plans',plan(c),ADMIN)
    assert state(c,july)['complete'] and state(c,september)['stale']
    september=confirm(c,start='2026-09-01')
    row=w.dataset(c)['plans'][-1]
    w.edit_record(c,row['id'],dict(row,note='Comment only'),ADMIN)
    assert state(c,september)['complete']
    row=w.dataset(c)['plans'][-1]
    w.edit_record(c,row['id'],dict(row,date='2026-07-10'),ADMIN)
    assert state(c,july)['stale'] and state(c,september)['stale']
    july=confirm(c,end='2026-07-31')
    row=w.dataset(c)['plans'][-1];w.edit_record(c,row['id'],row,ADMIN,delete=True)
    assert state(c,july)['stale']


def test_excel_noop_change_and_category(c,source):
    ident=confirm(c,'trips');w.ingest(c,copy.deepcopy(source));w.ingest(c,copy.deepcopy(source))
    assert state(c,ident)['complete']
    changed=copy.deepcopy(source);changed['trips'][0]['revenue']=4321;w.ingest(c,changed)
    assert state(c,ident)['stale']
    ident=confirm(c,'trips');row=w.dataset(c)['trips'][0]
    w.edit_record(c,row['record_id'],dict(category='Доплата',revision=row['revision']),ADMIN)
    assert state(c,ident)['stale']


def test_tt_noop_then_money_cancel_date_change(c):
    tt.apply(c,[raw()],'2026-08-01','2026-08-31')
    aug=confirm(c,'trips','2026-08-01','2026-08-31');sep=confirm(c,'trips','2026-09-01','2026-09-30')
    for _ in range(2):tt.apply(c,[raw()],'2026-08-01','2026-08-31')
    assert state(c,aug)['complete'] and state(c,sep)['complete']
    changed=dict(raw(),ClientSum='222')
    tt.apply(c,[changed],'2026-08-01','2026-08-31');assert state(c,aug)['stale']
    aug=confirm(c,'trips','2026-08-01','2026-08-31')
    tt.apply(c,[dict(changed,Status='Отмена')],'2026-08-01','2026-08-31');assert state(c,aug)['stale']
    aug=confirm(c,'trips','2026-08-01','2026-08-31')
    moved=dict(changed,BeginDateTime='2026-09-01 08:00:00',EndDateTime='2026-09-01 12:00:00')
    tt.apply(c,[moved],'2026-09-01','2026-09-30')
    assert state(c,aug)['stale'] and state(c,sep)['stale']


def test_empty_full_period_zeros_are_distinct(c):
    q={'from':'2026-08-01','to':'2026-08-31'}
    confirm(c,'plans',q['from'],q['to']);confirm(c,'trips',q['from'],q['to'])
    row=reports.comparison(w.dataset(c),q)['rows'][0]
    assert row['plan_revenue']==0 and row['delta_revenue']==900


def test_merge_invalidates_identity_even_without_amount_change(c):
    ident=confirm(c)
    new=w.save_catalog(c,'drivers',dict(name='Другой водитель'))
    old=w.dataset(c)['directories']['drivers'][0]['id'];w.merge_catalog(c,'drivers',old,new)
    assert state(c,ident)['stale']


@pytest.mark.parametrize('kind',['plans','trips','statuses'])
def test_stale_missing_invalid_and_current_delete(c,source,kind):
    if kind=='trips':w.create_records(c,kind,dict(source['trips'][0],id='manual'),ADMIN)
    elif kind=='statuses':w.create_records(c,kind,dict(date='2026-08-01',kind='vehicle',entity='А123АА777',reason='Сервис'),ADMIN)
    row=w.dataset(c)[kind][-1]
    w.edit_record(c,row['record_id'],dict(row,note='New edit'),ADMIN)
    for b in (row,{},dict(row,revision=True),dict(row,revision=str(row['revision']))):
        with pytest.raises(w.ConflictError):w.edit_record(c,row['record_id'],b,ADMIN,delete=True)
    fresh=next(r for r in w.dataset(c)[kind] if r['record_id']==row['record_id'])
    w.edit_record(c,row['record_id'],fresh,ADMIN,delete=True)
    assert not any(r['record_id']==row['record_id'] for r in w.dataset(c)[kind])
    with pytest.raises(w.ConflictError):w.edit_record(c,row['record_id'],fresh,ADMIN,delete=True)


def test_imported_trip_delete_forbidden(c):
    row=w.dataset(c)['trips'][0]
    with pytest.raises(ValueError,match='Исходная заявка'):w.edit_record(c,row['record_id'],row,ADMIN,delete=True)


def test_status_merge_group_version_and_membership_atomic(c):
    original=w.dataset(c)['directories']['drivers'][0]['id']
    other=w.save_catalog(c,'drivers',dict(name='Иванов И.'))
    for ident in (original,other):w.create_records(c,'statuses',dict(date='2026-08-01',kind='driver',entity_id=ident,reason='Сервис'),ADMIN)
    before=w.dataset(c)['statuses'][0]
    w.merge_catalog(c,'drivers',other,original)
    with pytest.raises(w.ConflictError):w.edit_record(c,before['record_id'],before,ADMIN,delete=True)
    group=w.dataset(c)['statuses'][0];assert len(group['related_ids'])==1
    # A linked row changed, while the primary revision is untouched.
    c.execute('update records set revision=revision+1 where id=?',(group['related_ids'][0],))
    with pytest.raises(w.ConflictError):w.edit_record(c,group['id'],group,ADMIN,delete=True)
    assert c.execute("select count(*) from records where kind='statuses' and deleted=0").fetchone()[0]==2
    group=w.dataset(c)['statuses'][0];w.edit_record(c,group['id'],group,ADMIN,delete=True)
    assert not w.dataset(c)['statuses']


@pytest.mark.parametrize('kind',['coverage','card_bindings','expenses'])
def test_extra_stale_delete_is_soft(c,kind):
    if kind=='coverage':ident=confirm(c)
    elif kind=='card_bindings':ident=w.save_extra(c,kind,dict(provider='neftm',card='card-1',vehicle='А123АА777',start='2026-08-01',end='2026-08-31'),ADMIN)
    else:ident=w.save_extra(c,kind,dict(vehicle='А123АА777',date='2026-08-01',category='Ремонт',amount=20),ADMIN)
    old=next(r for r in w.dataset(c)[kind] if r['id']==ident)
    b=dict(old,note='Changed')
    if kind=='coverage':b=confirmation(c,b)
    w.save_extra(c,kind,b,ADMIN,ident)
    with pytest.raises(w.ConflictError):w.delete_extra(c,kind,ident,old,ADMIN)
    fresh=next(r for r in w.dataset(c)[kind] if r['id']==ident)
    w.delete_extra(c,kind,ident,fresh,ADMIN)
    row=c.execute('select * from '+kind+' where id=?',(ident,)).fetchone()
    assert row['deleted']==1 and row['revision']==3


def test_two_connections_cannot_both_delete(tmp_path,source):
    path=tmp_path/'test.sqlite'
    with sqlite3.connect(path) as c:
        c.row_factory=sqlite3.Row;w.initialize(c,source);row=w.dataset(c)['plans'][0]
    def remove():
        try:
            with sqlite3.connect(path,timeout=5) as c:
                c.row_factory=sqlite3.Row;w.edit_record(c,row['id'],row,ADMIN,delete=True)
            return 'deleted'
        except w.ConflictError:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(lambda _:remove(),range(2)))==['conflict','deleted']


def test_http_conflict_csrf_and_preview(tmp_path,monkeypatch,source):
    from app import server
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server,'DB',tmp_path/'fleet.sqlite');monkeypatch.setattr(server,'load_excel',lambda:source)
    server.init();client=server.app.test_client();h={'X-CSRF-Token':'test'}
    with client.session_transaction() as session:session.update(uid=1,csrf='test')
    with server.db() as c:row=w.dataset(c)['plans'][0]
    url='/api/manual/'+row['id']
    assert client.delete(url,json=row).status_code==403
    assert client.delete(url,json={},headers=h).status_code==409
    assert client.put('/api/records/'+row['id'],json=dict(row,note='Changed'),headers=h).status_code==200
    assert client.delete(url,json=row,headers=h).status_code==409
    with server.db() as c:fresh=w.dataset(c)['plans'][0]
    assert client.delete(url,json=fresh,headers=h).status_code==200
    p=client.get('/api/workspace/coverage/preview?source=plans&start=2026-07-01&end=2026-07-31').json
    b=dict(p,complete=True,fingerprint_algorithm=p['algorithm'])
    result=client.post('/api/workspace/coverage',json=b,headers=h);assert result.status_code==200
    ident=result.json['id']
    assert client.delete('/api/workspace/coverage/'+ident,json={},headers=h).status_code==409
    assert client.delete('/api/workspace/coverage/'+ident,json={'revision':1},headers=h).status_code==200
    monkeypatch.setattr(server,'user',lambda:dict(id=2,role='viewer',vehicles=[]))
    assert client.get('/api/workspace/coverage/preview?source=plans&start=2026-07-01&end=2026-07-31').status_code==403


def test_busy_writer_is_conflict_without_partial_delete(tmp_path,source):
    path=tmp_path/'busy.sqlite'
    with sqlite3.connect(path) as init:
        init.row_factory=sqlite3.Row;w.initialize(init,source);row=w.dataset(init)['plans'][0]
    with sqlite3.connect(path) as owner,sqlite3.connect(path,timeout=0.01) as reader:
        owner.execute('BEGIN IMMEDIATE');reader.row_factory=sqlite3.Row
        with pytest.raises(w.ConflictError,match='сейчас обновляются'):
            w.edit_record(reader,row['id'],row,ADMIN,delete=True)
        assert reader.execute('select deleted from records where id=?',(row['id'],)).fetchone()[0]==0
