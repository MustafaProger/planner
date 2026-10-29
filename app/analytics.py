import collections
import datetime as dt
FIELDS=('revenue','payout','km','hours')
def measured_sum(rows,field):
    values=[r[field] for r in rows if r.get(field) is not None]
    return sum(values) if values else None

def complete_sum(rows,field):
    return measured_sum(rows,field) if rows and all(r.get(field) is not None for r in rows) else None

def metric_source(rows,field):
    return ' + '.join(sorted({r.get('sources',{}).get(field,'Excel') for r in rows if r.get(field) is not None})) or 'Нет данных'
def filtered(rows,q):
    return [r for r in rows if not r.get('cancelled') and (not q.get('from') or r.get('date','')>=q['from']) and (not q.get('to') or r.get('date','')<=q['to']) and all(not q.get(k) or r.get(k)==q[k] for k in ['vehicle','driver','client','type','carrier'])]
def aggregate(rows,key):
    out={}
    for r in rows:
        if r.get('cancelled'):continue
        label=r.get(key) or 'Не указано'
        if key=='pair':label=f"{r.get('vehicle','')} · {r.get('driver','')}"
        a=out.setdefault(label,dict(name=label,revenue=0,payout=0,km=0,hours=0,records=0,trips=0,days=set(),drivers=set(),missing={f:0 for f in FIELDS}))
        a['records']+=1;a['trips']+=r.get('category','Рейс')=='Рейс'
        if r.get('category','Рейс')=='Рейс':a['days'].add(r['date'])
        a['drivers'].add(r.get('driver',''))
        for f in FIELDS:
            if f in ('km','hours') and r.get('category','Рейс')!='Рейс':continue
            if r.get(f) is None:a['missing'][f]+=1
            a[f]+=r.get(f) or 0
    for a in out.values():
        a['known_sums']={f:a[f] for f in FIELDS}
        for f in FIELDS:
            if a['missing'][f]:a[f]=None
        a['days']=len(a['days']);a['drivers']=len(a['drivers']-{''})
        a['balance']=a['revenue']-a['payout'] if a['revenue'] is not None and a['payout'] is not None else None
        a['average_hours']=a['hours']/a['trips'] if a['trips'] and a['hours'] is not None else None
        a['rub_hour']=a['revenue']/a['hours'] if a['hours'] and a['revenue'] is not None else None
        a['rub_km']=a['revenue']/a['km'] if a['km'] and a['revenue'] is not None else None
        a['payout_percent']=100*a['payout']/a['revenue'] if a['revenue'] and a['payout'] is not None else None
    return sorted(out.values(),key=lambda a:-(a['revenue'] or 0))

def report(data,q):
    trips=filtered(data['trips'],q);plans=filtered(data['plans'],{k:v for k,v in q.items() if k not in ('client','type','carrier')});key=q.get('group','vehicle')
    if key not in ('vehicle','driver','pair','client','type','carrier','date','category','payment','payout_method','month','quarter','year','week','logist'):key='vehicle'
    for r in trips:
        iso_week=dt.date.fromisoformat(r['date']).isocalendar();r['week']=f'{iso_week.year}-W{iso_week.week:02d}'
        r['month']=r['date'][:7];r['year']=r['date'][:4];r['quarter']=r['date'][:4]+' Q'+str((int(r['date'][5:7])-1)//3+1)
    summary=aggregate([dict(r,total='Всего') for r in trips],'total')
    rows=aggregate(trips,key)
    if key=='vehicle' and not any(q.get(k) for k in ('driver','client','type','carrier')):
        satellite=filtered(data['satellite'],{k:v for k,v in q.items() if k in ('from','to','vehicle')})
        for row in rows:
            readings=[r for r in satellite if r['vehicle']==row['name']]
            row['sat_km']=measured_sum(readings,'km')
            row['sat_hours']=measured_sum(readings,'hours')
            row['sat_engine_hours']=measured_sum(readings,'engine_hours')
            row['fuel_liters']=measured_sum(readings,'fuel_liters')
            known_days={r['date'] for r in readings if r.get('km') is not None}
            trip_days={r['date'] for r in trips if r['vehicle']==row['name'] and r.get('category','Рейс')=='Рейс'}
            row['sat_days']=len(known_days) if readings else None
            row['missing_trip_days']=len(trip_days-known_days)
            row['delta_km']=row['km']-row['sat_km'] if row['km'] is not None and row['sat_km'] is not None and not row['missing_trip_days'] else None
            row['fuel_days']=len({r['date'] for r in readings if r.get('fuel_liters') is not None})
            row['engine_days']=len({r['date'] for r in readings if r.get('engine_hours') is not None})
            a=q.get('from') or min((r['date'] for r in readings),default=None)
            b=q.get('to') or max((r['date'] for r in readings),default=None)
            row['period_days']=(dt.date.fromisoformat(b)-dt.date.fromisoformat(a)).days+1 if a and b else 0
            both=[r for r in readings if r.get('fuel_liters') is not None and r.get('km') is not None]
            fuel_km=measured_sum(both,'km')
            row['fuel_l_per_100_km']=measured_sum(both,'fuel_liters')/fuel_km*100 if fuel_km else None
            row['fuel_ratio_days']=len({r['date'] for r in both})
            row['km_source']=metric_source(readings,'km')
            row['engine_source']=metric_source(readings,'engine_hours')
            row['fuel_source']=metric_source(readings,'fuel_liters')
    return dict(rows=rows,totals=summary[0] if summary else {},trips=trips,plans=plans)
def reconcile(data,q):
    tq={k:v for k,v in q.items() if k in ('from','to','vehicle')}
    tt=collections.defaultdict(list);sp=collections.defaultdict(list)
    for r in filtered(data['trips'],tq):
        if r['category']=='Рейс':tt[(r['vehicle'],r['date'])].append(r)
    for r in filtered(data['satellite'],tq):sp[(r['vehicle'],r['date'])].append(r)
    rows=[]
    for car,day in sorted(set(tt)|set(sp)):
        a=tt[(car,day)];b=sp[(car,day)]
        tk=complete_sum(a,'km');sk=measured_sum(b,'km');th=complete_sum(a,'hours');sh=measured_sum(b,'hours')
        engine=measured_sum(b,'engine_hours');fuel=measured_sum(b,'fuel_liters')
        if not a and sk is None and engine is None and fuel is None:continue
        rows.append(dict(vehicle=car,date=day,tt_km=tk,sat_km=sk,delta_km=tk-sk if tk is not None and sk is not None else None,
                         tt_hours=th,sat_hours=sh,delta_hours=th-sh if th is not None and sh is not None else None,
                         sat_engine_hours=engine,fuel_liters=fuel,fuel_l_per_100_km=fuel/sk*100 if fuel is not None and sk else None,
                         km_source=metric_source(b,'km'),engine_source=metric_source(b,'engine_hours'),fuel_source=metric_source(b,'fuel_liters'),
                         fuel_status=next((r['fuel_status'] for r in b if 'fuel_status' in r),'pending'),
                         trips=len(a),state='Нет пробега ТТ' if a and tk is None else 'Сопоставлено' if a and sk is not None else 'Нет спутника' if a else 'Нет заявок',orders=[r['id'] for r in a]))
    return rows
