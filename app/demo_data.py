"""Deterministic, entirely fictional fixtures for an isolated local database."""
import datetime as dt
import json
import random
import sqlite3
from pathlib import Path
from app import workspace as w

VERSION = 'charter-demo-v1'
PERIOD = ['2026-11-01', '2026-11-30']
STAMP = '2026-11-07T15:00:00+00:00'
SOURCE = 'Демонстрационные данные — не сведения компании'


def enabled():
    import os
    return os.environ.get('FLEET_DEMO') == '1' and os.environ.get('FLEET_LOCAL_PREVIEW') == '1'


def facts(data_dir):
    return json.loads((Path(data_dir) / 'demo-facts.json').read_text())


def seed(target, login_source):
    """Create once. Never replace existing demo edits or real records."""
    target = Path(target)
    if (target / 'fleet.sqlite').exists():
        if not (target / 'demo-facts.json').exists():
            raise ValueError('The target is not a demo database; refusing to replace it.')
        return facts(target)['summary']
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(0o700)
    rng = random.Random(20261107)
    c = sqlite3.connect(target / 'building.sqlite')
    c.row_factory = sqlite3.Row
    w.schema(c)
    c.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT UNIQUE,password TEXT,role TEXT,vehicles TEXT); CREATE TABLE snapshot(id INTEGER PRIMARY KEY,body TEXT); CREATE TABLE charter_state(id INTEGER PRIMARY KEY,revision INTEGER,body TEXT);')
    with sqlite3.connect(f'file:{Path(login_source).resolve()}?mode=ro', uri=True) as old:
        c.executemany('INSERT INTO users VALUES(?,?,?,?,?)', old.execute('SELECT id,name,password,role,vehicles FROM users').fetchall())
    empty = dict(trips=[], plans=[], statuses=[], satellite=[], routes=[], vehicles={}, drivers={}, meta=dict(files=[],issues=[]))
    c.execute('INSERT INTO snapshot VALUES(1,?)',(w.dump(empty),))
    c.executemany('INSERT INTO workspace_meta VALUES(?,?)',[('initialized','1'),('last_import',w.dump(dict(source=SOURCE,imported_at=STAMP,files=[],issues=[])))])
    def cat(kind, name, **kw):
        return w.add_catalog(c,kind,name,**kw)
    carriers = ['Чартер · демо', 'ООО Северный маршрут · демо', 'ИП Лебедев · демо', 'Самозанятый Орлов · демо']
    carrier_ids = [cat('carriers', n) for n in carriers]
    for n in carriers:cat('companies',n)
    types = ['1,5 тонны','2 тонны','5 тонн','10 тонн']
    type_ids = [cat('transport_types',n) for n in types]
    for n in ['ПРР','Доплата','Премия','Дополнительные работы','Удержание']:cat('transport_types',n)
    clients = ['Ритейл Север · демо','Почтовая сеть · демо','Маркет 24 · демо','ФармДоставка · демо','Мебельный дом · демо','Городская типография · демо']
    for n in clients:cat('clients',n)
    for n in w.REASONS:cat('reasons',n)
    names = ['Алексей Северный','Дмитрий Лесной','Илья Озёрный','Максим Береговой','Антон Речной','Роман Полянский','Павел Луговой','Сергей Горный','Олег Ветров','Иван Долинный','Никита Резервный']
    cars=[]; drivers=[]
    for i,name in enumerate(names):
        company=carriers[0 if i<4 or i==10 else 1 if i<7 else 2 if i==7 else 3] if i!=9 else ''
        ident=cat('drivers',name+' · демо',company=company,carrier_id=carrier_ids[carriers.index(company)] if company else '',placeholder=False)
        drivers.append(dict(id=ident,name=name+' · демо'))
    for i in range(10):
        company=carriers[0 if i<4 else 1 if i<7 else 2 if i==7 else 3] if i!=9 else ''
        typ=i%4
        name=f'А{101+i}АА777'
        ident=cat('vehicles',name,brand=['ГАЗель Next','Ford Transit','ГАЗон Next','КамАЗ'][typ],company=company,carrier_id=carrier_ids[carriers.index(company)] if company else '',transport_type_id=type_ids[typ] if i!=9 else '',resource_type='vehicle')
        cars.append(dict(id=ident,name=name,company=company,type=types[typ],norm=[13.5,15.2,21.5,28.0][typ]))
    # An intentionally incomplete record makes data-quality screens demonstrable.
    cat('drivers','Водитель без принадлежности · демо',company='',placeholder=False)
    routes=[]
    for i,name in enumerate(['Москва → Химки','Москва → Подольск','Москва → Тула','Москва → Рязань','Склад Север → торговые точки','Ночной межскладской','Склад Восток → терминал','Городской экспресс']):
        name+=' · демо';route_id=cat('routes',name,group=types[i%4],inactive_route=False)
        rate=dict(revenue=18000+i*2300,payout=4500+i*420,partner_payout=11500+i*1800,km=95+i*43,hours=5+i*.8,rate=900,partner_rate=1800)
        c.execute('INSERT INTO tariffs VALUES(?,?,?,?)',(f'demo-rate-{i}',route_id,'2026-01-01',w.dump(rate)))
        routes.append(dict(id=route_id,name=name,**rate))
    counts=dict(trips=0,charges=0,statuses=0,plans=0)
    def record(kind,ident,row):
        row=dict(row,source=SOURCE,origin='demo',demo=True)
        c.execute('INSERT INTO records(id,kind,body) VALUES(?,?,?)',(ident,kind,w.dump(w.attach_refs(row,w.catalogs(c)))))
    def status(day,i,reason,kind='vehicle',extra=False):
        entity=cars[i]['name'] if kind=='vehicle' else drivers[i]['name']
        ident=f'demo-status-{kind}-{i}-{day}-{reason}'
        record('statuses',ident,dict(id=ident,date=day,kind=kind,entity=entity,reason=reason,note=('Дополнительное событие после рейса' if extra else 'Учебный пример календарного статуса')+' · демо'))
        counts['statuses']+=1
    satellite=[];fuel=[];trip_days={};forced_work=set()
    start=dt.date(2026,1,1);end=dt.date(2026,11,30)
    for offset in range((end-start).days+1):
        day=start+dt.timedelta(days=offset);iso=day.isoformat()
        for i,car in enumerate(cars):
            # Every month has work, idle, service, missing, and a driver absence.
            code=(day.day+i*3)%29
            reason='Ремонт' if code in (6,7) else 'Нет заявки' if code in (12,13) else 'БезВодителя' if code==18 else 'Больничный' if code==23 else 'Выходной' if day.weekday()==6 else None
            missing=code==25
            work=(reason is None and not missing) or (i,iso) in forced_work
            if day.day==13 and i in (3,7):work=False;reason='Нет заявки';missing=False
            if day.day==7 and i==5:work=False;reason='Ремонт';missing=False
            # Controlled November scenarios for acceptance demonstrations.
            if day.month==11 and day.day in (5,10,14,18,20) and i in (0,1,2):work=True;reason=None;missing=False
            if work:
                count=2 if code%5==0 else 1
                total_km=0;total_hours=0
                for j in range(count):
                    km=round(65+i*21+rng.uniform(0,180),1);hours=round(3.4+km/60+rng.uniform(0,.9),1)
                    revenue=round((6500+km*(36+i*3))*(.82+day.month*.025+rng.random()*.13),2)
                    own=i<4;payout=round(revenue*(.24 if own else .64)+rng.uniform(100,800),2)
                    begin=f'{iso}T{7+j*7:02d}:00:00';finish=f'{iso}T{13+j*7:02d}:00:00'
                    if day.month==11 and day.day==14 and i==0 and j==0:
                        finish=f'{(day+dt.timedelta(days=1)).isoformat()}T16:00:00';km=480;hours=32;revenue=38500;payout=9800;forced_work.add((i,(day+dt.timedelta(days=1)).isoformat()))
                    if day.month==11 and day.day==10 and i==1:
                        begin=f'{iso}T00:00:00';finish=f'{(day+dt.timedelta(days=1)).isoformat()}T00:00:00';km=210;hours=24
                    ident=f'DEMO-{day:%m%d}-{i+1:02d}-{j+1}'
                    record('trips',ident,dict(id=ident,date=iso,start=begin,end=finish,vehicle=car['name'],driver=drivers[i]['name'],carrier=car['company'],type=car['type'],client=clients[(i+day.day//4)%len(clients)],revenue=revenue,payout=payout,driver_payout=payout if own else None,km=km,hours=hours,category='Рейс',payment='Безнал',payout_method='Безнал',route=routes[(i+day.day)%len(routes)]['name']))
                    total_km+=km;total_hours+=hours;counts['trips']+=1
                trip_days[(i,iso)]=total_km
                if code==9 or (day.month==11 and day.day==18 and i==0):status(iso,i,'Ремонт',extra=True)
                if day.day in (10,20,28):
                    charge=['ПРР','Премия','Доплата','Дополнительные работы'][(day.day+i)%4];amount=[1200,2500,1600,1900][i%4]
                    ident=f'DEMO-CHARGE-{i}-{iso}'
                    record('trips',ident,dict(id=ident,date=iso,start=f'{iso}T18:00:00',end=f'{iso}T19:00:00',vehicle=car['name'],driver=drivers[i]['name'],carrier=car['company'],type=charge,client=clients[(i+day.day//4)%len(clients)],category='Погрузка' if charge=='ПРР' else 'Доплата',revenue=amount*1.4,payout=amount,driver_payout=amount if i<4 else None,km=None,hours=1))
                    counts['charges']+=1
            else:
                total_km=0;total_hours=0
                if not missing:status(iso,i,reason);status(iso,i,reason,'driver')
            km=round(total_km*(1.035+rng.random()*.07),1) if work else 0.0
            engine=round(min(total_hours,15)+rng.uniform(.1,1),1) if work else 0
            if day.day==13 and i in (3,7):km=82.5;engine=3.5
            if day.day==7 and i==5:km=2.1;engine=7.8
            if day.month==11 and day.day==5 and i==0:km=3.4;engine=1.2
            if day.month==11 and day.day==10 and i==1:km=314.2;engine=13.4
            if not (day.day==20 and i==2):
                satellite.append(dict(date=iso,vehicle=car['name'],km=km,engine_hours=engine,movement_hours=round(engine*.7,1),stop_hours=round(engine*.3,1),hours=None,fuel_liters=round(km*car['norm']/100,1),source=SOURCE,sources={k:SOURCE for k in ('km','engine_hours','fuel_liters')},mileage_status='ok',fuel_status='ok',synced_at=STAMP,demo=True))
            if day.day in (3+i%3,10+i%3,17+i%3,24+i%3):
                liters=round(42+i*4+rng.uniform(0,15),2);price=round(66.5+day.month*.37+rng.random(),2)
                fuel.append(dict(id=f'demo-fuel-{i}-{iso}',provider='Демо-карты',date=iso,card=f'DEMO-{i+1:04d}',vehicle=car['name'],product='ДТ Евро · демо',liters=liters,amount=round(liters*price,2),operation='11',allocation='Демо-привязка',demo=True))
                if i==0 and day.day==10:fuel.append(dict(fuel[-1],id=f'demo-repeat-{iso}',liters=25,amount=round(25*price,2)))
    for day in ('2026-10-15','2026-11-12','2026-11-22'):
        fuel.append(dict(id='demo-unbound-'+day,provider='Демо-карты',date=day,card='DEMO-NO-LINK',vehicle='',product='ДТ Евро · демо',liters=55,amount=3905,operation='11',allocation='Нет привязки · учебный пример',demo=True))
    # Planner is populated as well, so the links to existing forms remain useful.
    for n in range(30):
        day=(dt.date(2026,11,1)+dt.timedelta(days=n)).isoformat()
        for i,car in enumerate(cars[:8]):
            route=routes[(n+i)%len(routes)];ident=f'demo-plan-{day}-{i}'
            record('plans',ident,dict(id=ident,date=day,vehicle=car['name'],driver=drivers[i]['name'],route=route['name'],slot='1',partner=i>=4,state='scheduled',**{k:route[k] for k in w.NUMBERS}))
            counts['plans']+=1
    reviews={}
    for day,i,state,comment in [('2026-11-05',0,'В работе','Учебный пример: проверяем показания трекера.'),('2026-11-10',1,'Обосновано','Учебный пример: согласован объезд закрытого участка.'),('2026-11-20',2,'Исправлено','Учебный пример: заявку на восстановление трекера выполнили.')]:
        kind='Заявка без движения' if i==0 else 'Перепробег' if i==1 else 'Нет спутниковых данных'
        key=f'{kind}|{cars[i]["name"]}|{day}'
        event=dict(status=state,comment=comment,author='Демо-логист',at=STAMP)
        reviews[key]=dict(event,vehicle=cars[i]['name'],history=[dict(event,status='Не проверено',comment='Синтетический сигнал создан для демонстрации.'),event])
    settings=dict(movement_threshold=10,excess_km=30,excess_percent=10,fuel_norms={r['name']:r['norm'] for r in cars})
    c.execute('INSERT INTO charter_state VALUES(1,1,?)',(w.dump(dict(settings=settings,reviews=reviews)),))
    c.commit();c.close()
    summary=dict(**counts,vehicles=len(cars),drivers=len(drivers)+1,carriers=len(carriers),clients=len(clients),satellite=len(satellite),fuel=len(fuel),from_date=start.isoformat(),to_date=end.isoformat())
    data=dict(version=VERSION,period=PERIOD,created_at=STAMP,source=SOURCE,satellite=satellite,fuel=fuel,summary=summary)
    (target/'demo-facts.json').write_text(w.dump(data))
    (target/'building.sqlite').replace(target/'fleet.sqlite')
    (target/'fleet.sqlite').chmod(0o600)
    return summary
