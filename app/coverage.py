"""Content-bound attestations. Poll timestamps and comments are not business changes."""
import hashlib
import json

ALGORITHM = 'fleet-period-v1'
FIELDS = ('date','start','end','category','state','cancelled','duplicate_review',
          'revenue','payout','km','hours','partner','slot','api_missing','api_list_omitted','logist')
REFERENCES = ('vehicle','driver','route','client','carrier','type','payment','payout_method')


def fingerprint(data, source, start, end):
    if source not in ('trips', 'plans'):
        raise ValueError('Выберите источник: заявки или план.')
    rows=[]
    for row in data.get(source, []):
        if not start <= row['date'] <= end:
            continue
        item={key:row.get(key) for key in FIELDS}
        for key in ('revenue','payout','km','hours'):
            if isinstance(item[key],(int,float)) and not isinstance(item[key],bool):item[key]=float(item[key])
        for key in ('cancelled','duplicate_review','partner','api_missing','api_list_omitted'):
            item[key]=bool(item[key])
        item['record_id']=row.get('record_id',row.get('id'))
        for key in REFERENCES:
            item[key]=row.get(key+'_id') or row.get(key) or None
        # A conflict changes whether the reviewed source set is trustworthy.
        item['api_conflict']=bool(row.get('api_conflict'))
        rows.append(item)
    rows.sort(key=lambda r:json.dumps(r,ensure_ascii=False,sort_keys=True))
    raw=json.dumps([ALGORITHM,source,start,end,rows],ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def preview(data, source, start, end):
    from app.analytics import aggregate
    selected=[r for r in data.get(source,[]) if start<=r['date']<=end]
    included=[dict(r,category='Рейс') for r in selected if r.get('state','scheduled') in ('scheduled','unassigned') and not r.get('duplicate_review')] if source=='plans' else [r for r in selected if not r.get('cancelled')]
    totals=aggregate([dict(r,total='Всего') for r in included],'total')
    summary=totals[0] if totals else dict(records=0,trips=0,revenue=0,payout=0,km=0,hours=0,known_sums={k:0 for k in ('revenue','payout','km','hours')},missing={k:0 for k in ('revenue','payout','km','hours')})
    return dict(source=source,start=start,end=end,algorithm=ALGORITHM,
                checked_fingerprint=fingerprint(data,source,start,end),record_count=len(selected),
                unresolved_count=sum(bool(r.get('duplicate_review') or r.get('api_missing') or r.get('api_conflict') or r.get('state') in ('unassigned','review')) for r in selected),
                excluded_count=len(selected)-len(included),summary=summary)


def evaluate(data, row):
    checked=row.get('checked_complete', row.get('complete',False))
    valid=(row.get('fingerprint_algorithm')==ALGORITHM and
           row.get('checked_fingerprint')==fingerprint(data,row['source'],row['start'],row['end']))
    stale=bool(checked and not valid)
    return dict(row,checked_complete=checked,complete=bool(checked and valid),stale=stale,
                state=('Данные изменились после проверки' if row.get('checked_fingerprint') else 'Требуется повторная проверка') if stale else
                      'Полнота подтверждена' if checked else 'Полнота не подтверждена')
