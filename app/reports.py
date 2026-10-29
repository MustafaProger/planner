"""Reports with explicit coverage, plan states, and no fabricated allocations."""
import collections
import datetime as dt
from app.analytics import aggregate, filtered, measured_sum
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
    return covered([r for r in d.get('coverage',[]) if r['source']==source and r['complete']],q.get('from'),q.get('to'))

def plan_rows(d,q):
    rows=filtered(d['plans'],{k:v for k,v in q.items() if k in ('from','to','vehicle','driver')})
    good=[r for r in rows if eligible(r)]
    key=q.get('group','vehicle')
    if key not in ('vehicle','driver','route','company','date','month','quarter','year'):key='vehicle'
    drivers={r['id']:r for r in d['directories']['drivers']}
    prepared=[]
    for r in good:
        x=dict(r,category='Рейс');x['company']=drivers.get(r.get('driver_id'),{}).get('company','')
        x['month']=r['date'][:7];x['year']=r['date'][:4];x['quarter']=r['date'][:4]+' Q'+str((int(r['date'][5:7])-1)//3+1)
        if x.get('driver','').casefold() in ('нет марш','заменить'):x['driver']='Не назначен'
        if x.get('vehicle','').casefold() in ('нет марш','заменить'):x['vehicle']='Не назначен'
        prepared.append(x)
    return {'rows':aggregate(prepared,key),'records':rows,'totals':aggregate([dict(r,total='Всего') for r in prepared],'total'),
            'excluded':len(rows)-len(good),'unassigned':sum(r.get('state')=='unassigned' for r in good)}

def comparison(d,q):
    key=q.get('group','vehicle')
    if key not in ('vehicle','driver','pair'):key='vehicle'
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
        r['state']='Сопоставимо' if pc and fc else 'Полнота периода не подтверждена'
        if not p and f:r['state']='Вне плана' if pc else 'Нет плана — факт показан отдельно'
        rows.append(r)
    return dict(rows=rows,plan_complete=pc,fact_complete=fc)

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

def economics(d,q,data_dir):
    from app.fuel_history import normalized
    ops,periods=normalized(data_dir);ops=[r for r in ops if in_period(r,q)]
    cats=d['directories'];bindings=d['card_bindings'];expenses=[]
    for e in d['expenses']:
        ref=lookup(cats,'vehicles',e['vehicle_id']);x=dict(e,vehicle=ref['name'] if ref else e['vehicle'])
        if in_period(x,q):expenses.append(x)
    for r in ops:
        matches=[b for b in bindings if b['provider']==r['provider'] and b['card']==r['card'] and b['start']<=r['date']<=b['end']]
        ref=lookup(cats,'vehicles',matches[0]['vehicle_id']) if len(matches)==1 else None
        r['vehicle']=ref['name'] if ref else '';r['allocation']='Привязана' if ref else 'Нет однозначной привязки'
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
