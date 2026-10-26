import collections
FIELDS=('revenue','payout','km','hours')
def filtered(rows,q):
    return [r for r in rows if (not q.get('from') or r.get('date','')>=q['from']) and (not q.get('to') or r.get('date','')<=q['to']) and all(not q.get(k) or r.get(k)==q[k] for k in ['vehicle','driver','client','type','carrier'])]
def aggregate(rows,key):
    out={}
    for r in rows:
        label=r.get(key) or 'Не указано'
        if key=='pair':label=f"{r.get('vehicle','')} · {r.get('driver','')}"
        a=out.setdefault(label,dict(name=label,revenue=0,payout=0,km=0,hours=0,records=0,trips=0,days=set(),drivers=set()))
        a['records']+=1;a['trips']+=r.get('category','Рейс')=='Рейс'
        if r.get('category','Рейс')=='Рейс':a['days'].add(r['date'])
        a['drivers'].add(r.get('driver',''))
        for f in FIELDS:
            if f in ('km','hours') and r.get('category','Рейс')!='Рейс':continue
            a[f]+=r.get(f) or 0
    for a in out.values():
        a['days']=len(a['days']);a['drivers']=len(a['drivers']-{''});a['balance']=a['revenue']-a['payout'];a['average_hours']=a['hours']/a['trips'] if a['trips'] else None;a['rub_hour']=a['revenue']/a['hours'] if a['hours'] else None;a['rub_km']=a['revenue']/a['km'] if a['km'] else None
    return sorted(out.values(),key=lambda a:-a['revenue'])
def report(data,q):
    trips=filtered(data['trips'],q);plans=filtered(data['plans'],{k:v for k,v in q.items() if k not in ('client','type','carrier')});key=q.get('group','vehicle')
    if key not in ('vehicle','driver','pair','client','type','carrier','date','category'):key='vehicle'
    summary=aggregate([dict(r,total='Всего') for r in trips],'total')
    rows=aggregate(trips,key)
    if key=='vehicle' and not any(q.get(k) for k in ('driver','client','type','carrier')):
        satellite=filtered(data['satellite'],{k:v for k,v in q.items() if k in ('from','to','vehicle')})
        for row in rows:
            readings=[r for r in satellite if r['vehicle']==row['name']]
            row['sat_km']=sum(r['km'] for r in readings) if readings else None
            row['sat_hours']=sum(r['hours'] or 0 for r in readings) if readings else None
            row['sat_days']=len({r['date'] for r in readings}) if readings else None
            row['delta_km']=row['km']-row['sat_km'] if readings else None
    return dict(rows=rows,totals=summary[0] if summary else {},trips=trips,plans=plans)
def reconcile(data,q):
    tq={k:v for k,v in q.items() if k in ('from','to','vehicle')}
    tt=collections.defaultdict(list);sp=collections.defaultdict(list)
    for r in filtered(data['trips'],tq):
        if r['category']=='Рейс':tt[(r['vehicle'],r['date'])].append(r)
    for r in filtered(data['satellite'],tq):sp[(r['vehicle'],r['date'])].append(r)
    rows=[]
    for car,day in sorted(set(tt)|set(sp)):
        a=tt[(car,day)];b=sp[(car,day)];tk=sum(r['km'] for r in a) if a else None;sk=sum(r['km'] for r in b) if b else None;th=sum(r['hours'] or 0 for r in a) if a else None;sh=sum(r['hours'] or 0 for r in b) if b else None
        rows.append(dict(vehicle=car,date=day,tt_km=tk,sat_km=sk,delta_km=tk-sk if a and b else None,tt_hours=th,sat_hours=sh,delta_hours=th-sh if a and b else None,trips=len(a),state='Сопоставлено' if a and b else 'Нет спутника' if a else 'Нет заявок',orders=[r['id'] for r in a]))
    return rows
