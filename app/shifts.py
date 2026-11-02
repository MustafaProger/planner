"""Confirmed driver/vehicle responsibility intervals, independent of order duration."""
import datetime as dt
import json
import uuid
from app.mileage import Conflict, dump, instant

METRICS=('km','engine_hours','movement_hours','fuel_liters')

def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS actual_shifts(id TEXT PRIMARY KEY,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS actual_shift_history(id TEXT,revision INTEGER,body TEXT NOT NULL,PRIMARY KEY(id,revision))')

def rows(c):
    if not c.execute("select 1 from sqlite_master where name='actual_shifts'").fetchone(): return []
    from app import workspace as ws
    cats=ws.catalogs(c);out=[]
    for r in c.execute('SELECT id,body,revision FROM actual_shifts WHERE deleted=0'):
        item=dict(json.loads(r[1]),id=r[0],revision=r[2])
        for key,kind in [('driver','drivers'),('vehicle','vehicles')]:
            entity=ws.lookup(cats,kind,item[key+'_id'])
            item[key]=entity['name'] if entity else 'Неизвестно'
            if entity:item[key+'_id']=entity['id']
        out.append(item)
    for row in out:
        row['conflicts']=[x['id'] for x in out if x['id']!=row['id'] and overlap(row,x) and (x['driver_id']==row['driver_id'] or x['vehicle_id']==row['vehicle_id'])]
        row['status']='conflict' if row['conflicts'] else 'confirmed'
    return out

def overlap(a,b): return a['start']<b['end'] and b['start']<a['end']

def save(c,b,user_id,ident=None):
    from app import workspace as ws
    if not isinstance(b,dict):raise ValueError('Ожидается интервал.')
    old=c.execute('select body,revision,deleted from actual_shifts where id=?',(ident,)).fetchone() if ident else None
    if ident and (not old or old[2] or type(b.get('revision')) is not int or b['revision']!=old[1]):raise Conflict('Смена изменена или удалена. Перечитайте список.')
    if b.get('confirmed') is not True: raise ValueError('Подтвердите фактический интервал по указанному источнику.')
    start,end=instant(b.get('start')),instant(b.get('end'))
    if start>=end:raise ValueError('Окончание должно быть позже начала.')
    source_ref=str(b.get('source_ref') or '').strip()
    if not source_ref or len(source_ref)>500:raise ValueError('Укажите документ или журнал, подтверждающий интервал (до 500 символов).')
    cats=ws.catalogs(c);data={}
    for key,kind in [('driver','drivers'),('vehicle','vehicles')]:
        entity=ws.lookup(cats,kind,b.get(key+'_id'),active=True)
        if not entity or entity.get('placeholder') or (key=='vehicle' and entity.get('resource_type','vehicle')!='vehicle'):raise ValueError('Выберите действующего водителя и автомобиль из справочника.')
        data[key+'_id']=entity['id']
    data.update(start=start,end=end,hours=(dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(start)).total_seconds()/3600,source_ref=source_ref,kind='responsibility_interval',confirmed_by=user_id,confirmed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    ident=ident or uuid.uuid4().hex;rev=old[1]+1 if old else 1
    if old:
        changed=c.execute('UPDATE actual_shifts SET body=?,revision=? WHERE id=? AND revision=? AND deleted=0',(dump(data),rev,ident,old[1])).rowcount
        if changed!=1:raise Conflict('Смена изменилась. Перечитайте список.')
    else:c.execute('INSERT INTO actual_shifts(id,body) VALUES(?,?)',(ident,dump(data)))
    c.execute('INSERT INTO actual_shift_history VALUES(?,?,?)',(ident,rev,dump(data)))
    return dict(data,id=ident,revision=rev)

def delete(c,ident,revision,user_id):
    old=c.execute('SELECT body,revision FROM actual_shifts WHERE id=? AND deleted=0',(ident,)).fetchone()
    if not old or type(revision) is not int or old[1]!=revision:raise Conflict('Смена изменена или удалена. Перечитайте список.')
    if c.execute('UPDATE actual_shifts SET deleted=1,revision=revision+1 WHERE id=? AND revision=? AND deleted=0',(ident,revision)).rowcount!=1:raise Conflict('Смена изменилась.')
    c.execute('INSERT INTO actual_shift_history VALUES(?,?,?)',(ident,revision+1,dump(dict(json.loads(old[0]),deleted=True,deleted_by=user_id))))

def allocate(shifts,measurements):
    """Each disjoint measurement is assigned whole once or retained on vehicle. No proration."""
    normalized=[]
    for index,m in enumerate(measurements):
        row=dict(m,measurement_id=str(m.get('measurement_id',index)))
        try:row.update(start=instant(m['start']),end=instant(m['end']))
        except (ValueError,KeyError):row.update(start='',end='')
        normalized.append(row)
    result=[];totals={k:{'available':0,'assigned':0,'unassigned':0} for k in METRICS};counts={k:0 for k in METRICS}
    for m in normalized:
        eligible=[];reason='Нет подтвержденного покрытия всего измеренного интервала.'
        if not m['start'] or m['start']>=m['end']:reason='Нет точных границ измерения с часовым поясом.'
        elif any(other is not m and other['vehicle_id']==m['vehicle_id'] and other['start'] and overlap(other,m) for other in normalized):reason='Измерения пересекаются; распределение требует проверки.'
        else:
            intersect=[s for s in shifts if s['vehicle_id']==m['vehicle_id'] and overlap(s,m)]
            eligible=[s for s in intersect if s['start']<=m['start'] and s['end']>=m['end'] and not s.get('conflicts') and not any(o['id']!=s['id'] and o['driver_id']==s['driver_id'] and overlap(o,s) for o in shifts)]
            if len(intersect)!=1 or len(eligible)!=1:eligible=[]
        owner=eligible[0] if len(eligible)==1 else None
        result.append(dict(m,driver_id=owner['driver_id'] if owner else None,shift_id=owner['id'] if owner else None,allocation='assigned' if owner else 'unassigned',reason='' if owner else reason))
        for metric in METRICS:
            if m.get(metric) is not None:
                counts[metric]+=1
                totals[metric]['available']+=m[metric];totals[metric]['assigned' if owner else 'unassigned']+=m[metric]
    for metric in METRICS:
        if not counts[metric]:totals[metric]={key:None for key in ('available','assigned','unassigned')}
    return {'measurements':result,'totals':totals,'measured_cells':counts}

def daily_measurements(dataset):
    # Only provider-confirmed daily cells; Excel date-only aggregates lack precise boundaries.
    result=[]
    by_name={v['name']:v['id'] for v in dataset['directories']['vehicles']}
    for row in dataset['satellite']:
        source=row.get('sources',{})
        if not any(source.get(k)=='ГЛОНАССсофт API' for k in METRICS):continue
        day=dt.date.fromisoformat(row['date']);ident=row.get('vehicle_id') or by_name.get(row['vehicle'])
        if not ident:continue
        result.append(dict(vehicle_id=ident,vehicle=row['vehicle'],date=row['date'],measurement_id=ident+':'+row['date'],start=day.isoformat()+'T00:00:00+03:00',end=(day+dt.timedelta(days=1)).isoformat()+'T00:00:00+03:00',source='ГЛОНАССсофт API · сутки UTC+03',**{k:row.get(k) if source.get(k)=='ГЛОНАССсофт API' else None for k in METRICS}))
    return result
