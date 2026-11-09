"""Reports with explicit coverage, plan states, and no fabricated allocations."""
import collections
import datetime as dt
from app.analytics import aggregate, filtered, measured_sum, group_label, metric_source, reconcile
from app.workspace import lookup, natural

def in_period(r,q):return (not q.get('from') or r['date']>=q['from']) and (not q.get('to') or r['date']<=q['to'])
def eligible(r):return r.get('state','scheduled') in ('scheduled','unassigned') and not r.get('duplicate_review')
def covered(periods,a,b,start='start',end='end'):
    if not a or not b or a>b:return False
    at=dt.date.fromisoformat(a);last=dt.date.fromisoformat(b)
    for p in sorted(periods,key=lambda x:x[start]):
        x,y=dt.date.fromisoformat(p[start]),dt.date.fromisoformat(p[end])
        if x>at:break
        if y>=at:
            if y>=last:return True
            at=y+dt.timedelta(days=1)
    return False

def coverage(d,q,source):
    from app.coverage import evaluate
    return covered([r for r in d.get('coverage',[]) if r['source']==source and evaluate(d,r)['complete']],q.get('from'),q.get('to'))

def report_group(q,mode):
    key=q.get('group','vehicle')
    allowed=('vehicle','driver','pair') if mode=='comparison' else ('vehicle','driver','route','company','date','month','quarter','year')
    return key if key in allowed else 'vehicle'

def selected_plans(d,q):
    return filtered(d['plans'],{k:v for k,v in q.items() if k in ('from','to','vehicle','driver')})

def prepare_plans(d,rows):
    drivers={r['id']:r for r in d['directories']['drivers']}
    prepared=[]
    for r in rows:
        x=dict(r,category='Рейс');x['company']=drivers.get(r.get('driver_id'),{}).get('company','')
        x['month']=r['date'][:7];x['year']=r['date'][:4];x['quarter']=r['date'][:4]+' Q'+str((int(r['date'][5:7])-1)//3+1)
        if x.get('driver','').casefold() in ('нет марш','заменить'):x['driver']='Не назначен'
        if x.get('vehicle','').casefold() in ('нет марш','заменить'):x['vehicle']='Не назначен'
        prepared.append(x)
    return prepared

def plan_rows(d,q):
    rows=selected_plans(d,q)
    good=[r for r in rows if eligible(r)]
    key=report_group(q,'plans')
    prepared=prepare_plans(d,good)
    return {'rows':aggregate(prepared,key),'records':rows,'totals':aggregate([dict(r,total='Всего') for r in prepared],'total'),
            'excluded':len(rows)-len(good),'unassigned':sum(r.get('state')=='unassigned' for r in good)}

def comparison(d,q):
    key=report_group(q,'comparison')
    plans=[r for r in filtered(d['plans'],q) if eligible(r)]
    facts=[r for r in filtered(d['trips'],q) if r['category']=='Рейс']
    pp={r['name']:r for r in aggregate([dict(x,category='Рейс') for x in plans],key)}
    ff={r['name']:r for r in aggregate(facts,key)}
    pc=coverage(d,q,'plans');fc=coverage(d,q,'trips');rows=[]
    unresolved=any(r.get('duplicate_review') or r.get('state') in ('review','unassigned') for r in filtered(d['plans'],q))
    pc=pc and not unresolved
    for name in sorted(set(pp)|set(ff)):
        p,f=pp.get(name),ff.get(name);r=dict(name=name,plan_complete=pc,fact_complete=fc)
        for field in ('trips','days','revenue','payout','km','hours'):
            r['plan_'+field]=p[field] if p else 0 if pc else None
            r['fact_'+field]=f[field] if f else 0 if fc else None
            r['delta_'+field]=r['fact_'+field]-r['plan_'+field] if pc and fc and r['fact_'+field] is not None and r['plan_'+field] is not None else None
        r['delta_reasons']={field:('Полнота плана не подтверждена или есть спорные назначения' if not pc else 'Полнота факта не подтверждена' if not fc else 'Нет полного показателя плана' if r['plan_'+field] is None else 'Нет полного показателя факта' if r['fact_'+field] is None else '') for field in ('trips','days','revenue','payout','km','hours')}
        r['state']='Сопоставимо' if pc and fc else 'Полнота периода не подтверждена'
        if not p and f:r['state']='Вне плана' if pc else 'Нет плана — факт показан отдельно'
        rows.append(r)
    return dict(rows=rows,plan_complete=pc,fact_complete=fc)

def detail_period(q):
    """Validate new read-only routes before selecting a report snapshot."""
    for key in ('from','to'):
        if q.get(key) and dt.date.fromisoformat(q[key]).isoformat()!=q[key]:
            raise ValueError('Укажите дату в формате ГГГГ-ММ-ДД.')
    if q.get('from') and q.get('to') and q['from']>q['to']:
        raise ValueError('Начало периода должно быть не позже окончания.')

def plan_exclusion(row):
    if row.get('duplicate_review'):return 'Возможный повтор — не включен в итог'
    return {'cancelled':'Назначение отменено','no_route':'Маршрут не выполняется',
            'review':'Назначение ожидает проверки'}.get(row.get('state'),'Состояние назначения не включено в итог')

def report_details(d,q):
    """Explain one row without narrowing its original coverage/filter scope."""
    mode=q.get('mode','plans')
    if mode not in ('plans','comparison'):raise ValueError('Детализация доступна для сводки плана и план–факта.')
    detail_period(q)
    if 'row' not in q:raise ValueError('Выберите строку отчета.')
    key=report_group(q,mode)
    result=plan_rows(d,q) if mode=='plans' else comparison(d,q)
    summary=next((r for r in result['rows'] if r['name']==q['row']),None)
    if summary is None:return None
    plans=selected_plans(d,q) if mode=='plans' else filtered(d['plans'],q)
    prepared=prepare_plans(d,plans) if mode=='plans' else plans
    selected=[r for r,x in zip(plans,prepared) if group_label(x,key)==q['row']]
    facts=[] if mode=='plans' else [r for r in filtered(d['trips'],q) if group_label(r,key)==q['row']]
    return dict(mode=mode,group=key,name=q['row'],summary=summary,
                scope={k:q.get(k,'') for k in ('from','to','vehicle','driver')},
                plans=[r for r in selected if eligible(r)],
                trips=[r for r in facts if r.get('category')=='Рейс'],
                excluded_plans=[dict(record=r,reason=plan_exclusion(r)) for r in selected if not eligible(r)],
                excluded_trips=[dict(record=r,reason='Начисление учитывается в статистике денег, но не в сравнении рейсов') for r in facts if r.get('category')!='Рейс'],
                plan_complete=result.get('plan_complete'),fact_complete=result.get('fact_complete'))

SATELLITE_METRICS=('km','hours','engine_hours','movement_hours','stop_hours','fuel_liters')
SATELLITE_DETAIL_FIELDS=('vehicle','date','start','end','km','hours','engine_hours','movement_hours','stop_hours',
                         'idle_hours','fuel_liters','odometer_start','odometer_end','source','sources',
                         'synced_at','mileage_status','fuel_status')

def reconcile_details(d,q):
    """Show measurements received from the API."""
    car,day=q.get('vehicle'),q.get('date')
    if not car or not day:raise ValueError('Укажите автомобиль и дату сверки.')
    if dt.date.fromisoformat(day).isoformat()!=day:raise ValueError('Укажите дату в формате ГГГГ-ММ-ДД.')
    scope=dict(vehicle=car,**{'from':day,'to':day})
    summary=next((r for r in reconcile(d,scope) if r['vehicle']==car and r['date']==day),None)
    if summary is None:return None
    facts=filtered(d['trips'],scope)
    effective=filtered(d['satellite'],scope)
    usage={field:dict(value=measured_sum(effective,field),source=metric_source(effective,field)) for field in SATELLITE_METRICS}
    rows=[]
    for r in effective:
        x={k:r[k] for k in SATELLITE_DETAIL_FIELDS if k in r}
        for label,field in (('km','km'),('engine','engine_hours'),('fuel','fuel_liters'),('hours','hours')):
            x[label+'_source']=metric_source([r],field)
        rows.append(x)
    return dict(vehicle=car,date=day,summary=summary,trips=[r for r in facts if r.get('category')=='Рейс'],
                other_trips=[dict(record=r,reason='Начисление не участвует в сверке рейсов со спутником') for r in facts if r.get('category')!='Рейс'],
                satellite=rows,satellite_raw=[],metric_usage=usage)

def downtime(d,q):
    kind=q.get('entity','vehicle');kind=kind if kind in ('vehicle','driver') else 'vehicle'
    trips=[r for r in filtered(d['trips'],q) if r['category']=='Рейс']
    statuses=[r for r in d['statuses'] if r['kind']==kind and in_period(r,q) and (not q.get(kind) or r['entity']==q[kind])]
    names=sorted({r.get(kind,'') for r in trips}|{r['entity'] for r in statuses});out=[]
    for name in names:
        if not name:continue
        ts=[r for r in trips if r.get(kind)==name];ss=[r for r in statuses if r['entity']==name]
        work={r['date'] for r in ts};idle={r['date'] for r in ss}
        clients=collections.Counter(r['client'] for r in ts);reasons={x:len({r['date'] for r in ss if r['reason']==x}) for x in sorted({r['reason'] for r in ss})}
        out.append(dict(name=name,trips=len(ts),work_days=len(work),status_days=len(idle),overlap_days=len(work&idle),reasons=reasons,clients=dict(clients)))
    return dict(rows=out,entity=kind)

def fuel_operations(d,q,data_dir):
    from app.fuel_history import normalized
    ops,periods=normalized(data_dir);ops=[r for r in ops if in_period(r,q)]
    cats=d['directories'];bindings=collections.defaultdict(list)
    for binding in d['card_bindings']:
        bindings[binding['provider'],binding['card']].append(binding)
    for r in ops:
        matches=[b for b in bindings.get((r['provider'],r['card']), ()) if b['start']<=r['date']<=b['end']]
        ref=lookup(cats,'vehicles',matches[0]['vehicle_id']) if len(matches)==1 else None
        r['vehicle']=ref['name'] if ref else '';r['allocation']='Привязана' if ref else 'Нет однозначной привязки'
    return ops,periods

def economics(d,q,data_dir):
    ops,periods=fuel_operations(d,q,data_dir)
    cats=d['directories'];expenses=[]
    for e in d['expenses']:
        ref=lookup(cats,'vehicles',e['vehicle_id']);x=dict(e,vehicle=ref['name'] if ref else e['vehicle'])
        if in_period(x,q):expenses.append(x)
    facts=filtered(d['trips'],{k:v for k,v in q.items() if k in ('from','to','vehicle')})
    base={r['name']:r for r in aggregate(facts,'vehicle')};names=set(base)|{r['vehicle'] for r in ops+expenses if r['vehicle']}
    out=[]
    for name in sorted(names):
        if q.get('vehicle') and name!=q['vehicle']:continue
        a=base.get(name,{});p=[r for r in ops if r['vehicle']==name];e=[r for r in expenses if r['vehicle']==name]
        purchases=measured_sum(p,'amount');other=sum(r['amount'] for r in e)
        profit=a.get('balance')
        out.append(dict(name=name,revenue=a.get('revenue'),payout=a.get('payout'),purchases=purchases,liters=measured_sum(p,'liters'),other_expenses=other,
                        known_cost_balance=profit-(purchases or 0)-other if profit is not None else None,
                        unknown_operations=sum(r['amount'] is None for r in p),operations=len(p),state='После известных затрат; не чистая прибыль'))
    return dict(rows=out,operations=[r for r in ops if not q.get('vehicle') or r['vehicle']==q['vehicle']],
                unassigned=sum(not r['vehicle'] for r in ops),unknown=sum(r['amount'] is None for r in ops),
                coverage={k:covered(v,q.get('from'),q.get('to'),'from','to') for k,v in periods.items()})

def quality(d,q):
    rows=[]
    for r in filtered(d['plans'],q):
        if not in_period(r,q):continue
        if r.get('duplicate_review'):rows.append(dict(kind='plans',id=r['id'],date=r['date'],object=r['vehicle'],issue='Повтор назначения: задайте номер отдельной смены или отмените лишнюю запись',record=r))
        elif r.get('state')=='unassigned':rows.append(dict(kind='plans',id=r['id'],date=r['date'],object=r['route'],issue='Не назначен водитель или ресурс',record=r))
        elif r.get('state')=='review':rows.append(dict(kind='plans',id=r['id'],date=r['date'],object=r.get('route') or r.get('vehicle',''),issue='Назначение требует проверки: уточните ресурс, водителя, маршрут и состояние по источнику',record=r))
    for r in filtered(d['trips'],q):
        if not in_period(r,q):continue
        if r['category']=='Рейс' and (not r.get('vehicle') or (r.get('payout') or 0)<0 or (r.get('revenue') or 0)<0):
            rows.append(dict(kind='trips',id=r['record_id'],date=r['date'],object=r['id'],issue='Проверьте категорию: отрицательная сумма или нет машины',record=r))
    for r in filtered(d['trips'],q):
        if r.get('api_list_omitted'):
            rows.append(dict(kind='trips',id=r['record_id'],date=r['date'],object=r['id'],issue='Получена по ID, отсутствует в списке ТТ. Полнота списка не подтверждена.',record=r))
        if r.get('api_conflict'):
            rows.append(dict(kind='trips',id=r['record_id'],date=r['date'],object=r['id'],issue='Есть версия API с тем же ID. Локальная заявка сохранена; в итогах учитывается один раз.',record=r))
        if r.get('api_missing') or r.get('origin')=='transtrade' and (r.get('km') is None or r.get('revenue') is None or r.get('payout') is None):
            rows.append(dict(kind='trips',id=r['record_id'],date=r['date'],object=r['id'],issue='Не вернулась из API — прежняя запись сохранена' if r.get('api_missing') else 'API: есть отсутствующие показатели; не равны нулю',record=r))
    for kind in ('drivers','vehicles'):
        for r in d['directories'][kind]:
            if not r.get('archived') and (r.get('placeholder') or r.get('resource_type')=='placeholder'):
                rows.append(dict(kind=kind,id=r['id'],date='',object=r['name'],issue='Служебное обозначение; не предлагается для нового назначенного рейса'))
    return dict(rows=rows)

def build(d,q,data_dir):
    mode=q.get('mode','plans')
    if mode=='comparison':return comparison(d,q)
    if mode=='downtime':return downtime(d,q)
    if mode=='economics':return economics(d,q,data_dir)
    if mode=='quality':return quality(d,q)
    return plan_rows(d,q)
