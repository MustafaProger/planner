"""Persistent editable workspace. Source rows and frozen plan rates survive imports."""
import collections
import copy
import datetime as dt
import hashlib
import json
import math
import re
import uuid

KINDS = ('vehicles', 'drivers', 'routes', 'companies', 'clients', 'carriers',
         'transport_types', 'payment_methods', 'reasons')
REASONS = ['Отпуск','Больничный','Выходной','Сервис','Ремонт','Нет заявки','Пересменка','БезВодителя','Другое']
NUMBERS = ('revenue','payout','partner_payout','km','hours','rate','partner_rate')
STATES = ('scheduled','unassigned','no_route','cancelled','review')
PLACEHOLDERS = {'нет марш','заменить','нет маршрута'}
REFS = {'vehicle':'vehicles','driver':'drivers','route':'routes','client':'clients',
        'carrier':'carriers','type':'transport_types','payment':'payment_methods','payout_method':'payment_methods'}

def body(value):
    if not isinstance(value,dict):raise ValueError('Ожидается объект записи.')
    for key in ('archived','partner','inactive_route','complete'):
        if key in value and type(value[key]) is not bool:raise ValueError('Некорректное логическое значение.')

def dump(value): return json.dumps(value, ensure_ascii=False, sort_keys=True)
def uid(kind, *parts): return kind + ':' + hashlib.sha256(dump(parts).encode()).hexdigest()[:24]
def today(): return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).date().isoformat()
def reason(value): return str(value or '').replace('Простой','').replace('НетЗаявки','Нет заявки').strip()
def iso(value):
    try: return dt.date.fromisoformat(str(value)).isoformat()
    except (ValueError,TypeError): raise ValueError('Укажите корректную дату.') from None
def numeric(value, nullable=False):
    if isinstance(value,bool):raise ValueError('Введите число.')
    if value in (None,'') and nullable:return None
    try: result=float(value)
    except (ValueError,TypeError):raise ValueError('Введите число.') from None
    if not math.isfinite(result) or result<0:raise ValueError('Число должно быть конечным и неотрицательным.')
    return result
def schema(c):
    c.executescript('''
      CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS catalog(id TEXT PRIMARY KEY,kind TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0);
      CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
      CREATE TABLE IF NOT EXISTS tariffs(id TEXT PRIMARY KEY,route_id TEXT NOT NULL,effective_from TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(route_id,effective_from));
      CREATE TABLE IF NOT EXISTS coverage(id TEXT PRIMARY KEY,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE IF NOT EXISTS card_bindings(id TEXT PRIMARY KEY,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS expenses(id TEXT PRIMARY KEY,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0);
    ''')

def catalogs(c):
    out={kind:[] for kind in KINDS}
    for r in c.execute('select * from catalog'):
        out[r['kind']].append(dict(json.loads(r['body']),id=r['id'],revision=r['revision']))
    for kind in ('vehicles','drivers'):
        for row in out[kind]:
            company=lookup(out,'companies',row.get('company'))
            if company:row['company']=company['name']
    return out

def lookup(cats, kind, value, active=False):
    if not value:return None
    rows=cats[kind];row=next((r for r in rows if r['id']==value or value==r['name'] or value in r.get('aliases',[])),None)
    seen=set()
    while row and row.get('merged_into'):
        if row['id'] in seen:raise ValueError('Циклическое соответствие справочника.')
        seen.add(row['id']);row=next((r for r in rows if r['id']==row['merged_into']),None)
    return row if row and (not active or not row.get('archived')) else None

def add_catalog(c, kind, name, **fields):
    name=str(name or '').strip()
    if not name:return None
    # Seed only. Never overwrite a user-maintained entry on a later import.
    cat=catalogs(c);old=lookup(cat,kind,name)
    if old:return old['id']
    ident=uid(kind,name)
    c.execute('insert into catalog(id,kind,body) values(?,?,?)',
              (ident,kind,dump(dict(name=name,aliases=[],archived=False,**fields))))
    return ident

def seed_catalog(c,d):
    # Build one in-memory index instead of querying per source row.
    cats=catalogs(c);index={k:{v:r['id'] for r in rows for v in [r['name'],*r.get('aliases',[])]} for k,rows in cats.items()}
    def put(kind,name,**fields):
        name=str(name or '').strip()
        if not name:return None
        if name in index[kind]:return index[kind][name]
        ident=uid(kind,name);index[kind][name]=ident
        c.execute('insert into catalog(id,kind,body) values(?,?,?)',(ident,kind,dump(dict(name=name,aliases=[],archived=False,**fields))))
        return ident
    for name,company in d['drivers'].items():
        put('companies',company)
        put('drivers',name,company=company,partner=company=='Партнёр',placeholder=name.casefold() in PLACEHOLDERS)
    for name,legacy in d['vehicles'].items():
        detail=d.get('vehicle_details',{}).get(name,{})
        company=detail.get('company',legacy if legacy in ('Партнёр','Чартер ООО') else '')
        brand=detail.get('brand','' if company else legacy)
        put('companies',company)
        typ='vehicle' if re.fullmatch(r'[A-ZА-Я]\d{3}[A-ZА-Я]{2}\d{2,3}',name) else 'partner'
        if name.casefold() in PLACEHOLDERS or legacy=='Статус':typ='placeholder'
        if legacy in ('ДопРаботы','Штрафы','Удержание','ГСМ (удержано)'):typ='service'
        put('vehicles',name,brand=brand,company=company,resource_type=typ)
    for r in d['routes']:
        ident=put('routes',r['id'],group=r.get('group',''),inactive_route=bool(re.search('нет марш',r['id'],re.I)))
        if not c.execute('select 1 from tariffs where route_id=?',(ident,)).fetchone():
            c.execute('insert into tariffs values(?,?,?,?)',(uid('rate',ident,'0001-01-01'),ident,'0001-01-01',dump({k:r.get(k) for k in NUMBERS})))
    for r in d['trips']:
        for field,kind in REFS.items():
            if field not in ('vehicle','driver','route'):put(kind,r.get(field,''))
    for name in REASONS:put('reasons',name)
    for r in d['statuses']:put('reasons',reason(r['reason']))

def attach_refs(row,cats):
    row=copy.deepcopy(row)
    for field,kind in REFS.items():
        ref=lookup(cats,kind,row.get(field+'_id') or row.get(field))
        if ref:row[field+'_id']=ref['id']
    if row.get('kind') in ('vehicle','driver'):
        ref=lookup(cats,row['kind']+'s',row.get('entity_id') or row.get('entity'))
        if ref:row['entity_id']=ref['id']
    return row

def normalize_plan(r):
    r=copy.deepcopy(r)
    r.setdefault('state','no_route' if re.search('нет марш',r.get('route',''),re.I) else
                 'unassigned' if not r.get('vehicle') or not r.get('driver') or r.get('driver','').casefold() in PLACEHOLDERS or r.get('vehicle','').casefold() in PLACEHOLDERS else 'scheduled')
    return r

def natural(kind,r):
    if kind=='trips':return (str(r['id']),)
    if kind=='plans':return tuple(r.get(k+'_id',r.get(k,'')) for k in ('date','vehicle','driver','route'))+(r.get('slot',''),)
    if kind=='statuses':return (r['date'],r['kind'],r.get('entity_id',r['entity']),reason(r['reason']))
    return (r['vehicle'],r.get('start',r['date']),r.get('end',''),r.get('object',''))

def ingest(c,d, initial=False):
    seed_catalog(c,d);cats=catalogs(c)
    for kind in ('trips','plans','statuses','satellite'):
        occurrences=collections.Counter()
        manual_keys={natural(kind,json.loads(x['body'])) for x in c.execute('select body from records where kind=?',(kind,)) if json.loads(x['body']).get('origin')=='manual'}
        for source in d[kind]:
            r=attach_refs(source,cats)
            if kind=='plans':r=normalize_plan(r)
            if kind=='statuses':r['reason']=reason(r['reason'])
            key=natural(kind,r);occurrences[key]+=1
            ident=uid(kind,key,occurrences[key] if kind in ('plans','satellite') else 1)
            existing=c.execute('select * from records where id=?',(ident,)).fetchone()
            if existing:
                old=json.loads(existing['body'])
                if kind in ('plans','statuses'):
                    # Source identity is stable. Keep edited/deleted records and frozen tariffs.
                    continue
                if old.get('user_edited') or old.get('origin')=='transtrade':continue
                if kind=='trips' and old.get('category_override'):r.update(category=old['category_override'],category_override=old['category_override'])
                for field in ('origin','source_id','created_by','original_category'):r[field]=old.get(field)
                if dump(r)!=existing['body']:c.execute('update records set body=?,revision=revision+1 where id=?',(dump(r),ident))
            else:
                if kind in ('plans','statuses','trips'):
                    # A manual entry copied into Excel is the same business event, not a second one.
                    if key in manual_keys:continue
                r['origin']='excel';r['source_id']=source.get('id');r['created_by']=None
                c.execute('insert into records(id,kind,body) values(?,?,?)',(ident,kind,dump(r)))
    meta=copy.deepcopy(d['meta']);meta['source']='Рабочая база'
    c.execute('insert or replace into workspace_meta values(?,?)',('last_import',dump(meta)))

def initialize(c,d,legacy_manual=()):
    schema(c)
    if c.execute("select 1 from workspace_meta where key='initialized'").fetchone():return
    ingest(c,d,True)
    for old in legacy_manual:
        r=attach_refs(json.loads(old['body']),catalogs(c));r.update(origin='manual',created_by=old['created_by'],source='Введено в приложении')
        if old['kind']=='statuses':r['reason']=reason(r['reason'])
        c.execute('insert or ignore into records(id,kind,body,deleted) values(?,?,?,?)',(old['id'],old['kind'],dump(r),old['deleted']))
    c.execute("insert into workspace_meta values('initialized','1')")

def current_rate(c, route_id, date):
    row=c.execute('select * from tariffs where route_id=? and effective_from<=? order by effective_from desc limit 1',(route_id,date)).fetchone()
    if not row:raise ValueError('Нет тарифа маршрута на выбранную дату. Добавьте тариф.')
    return dict(json.loads(row['body']),tariff_id=row['id'],effective_from=row['effective_from'])

def resolve_row(r,cats):
    for field,kind in REFS.items():
        ref=lookup(cats,kind,r.get(field+'_id') or r.get(field))
        if ref:r[field]=ref['name'];r[field+'_id']=ref['id']
    if r.get('kind') in ('vehicle','driver'):
        ref=lookup(cats,r['kind']+'s',r.get('entity_id') or r.get('entity'))
        if ref:r['entity']=ref['name'];r['entity_id']=ref['id']
    return r

def dataset(c):
    cats=catalogs(c)
    d={k:[] for k in ('trips','plans','statuses','satellite')}
    d.update(directories=cats,vehicles={r['name']:r.get('company') or r.get('brand','') for r in cats['vehicles'] if not r.get('merged_into')},
             drivers={r['name']:r.get('company','') for r in cats['drivers'] if not r.get('merged_into')},routes=[],meta=json.loads(c.execute("select body from workspace_meta where key='last_import'").fetchone()[0]))
    for row in c.execute('select * from records where deleted=0'):
        r=resolve_row(json.loads(row['body']),cats);r.update(record_id=row['id'],revision=row['revision'])
        if row['kind']!='trips':r['id']=row['id']
        if row['kind']=='plans':r=normalize_plan(r)
        d[row['kind']].append(r)
    # Entity merges can collapse statuses. Keep all provenance, display/count each reason/day once.
    unique={}
    for r in d['statuses']:
        key=natural('statuses',r)
        if key in unique:
            unique[key].setdefault('related_ids',[]).append(r['id']);unique[key]['source']+='; '+r.get('source','')
        else:unique[key]=r
    d['statuses']=list(unique.values())
    groups=collections.defaultdict(list)
    for r in d['plans']:
        if r['state']!='cancelled':groups[natural('plans',r)].append(r)
    for rows in groups.values():
        if len(rows)>1:
            for r in rows:r['duplicate_review']=True
    for r in cats['routes']:
        try:rate=current_rate(c,r['id'],today())
        except ValueError:rate={k:None for k in NUMBERS}
        d['routes'].append(dict(rate,id=r['name'],uid=r['id'],group=r.get('group',''),archived=r.get('archived',False),inactive_route=r.get('inactive_route',False)))
    d['tariffs']=[dict(json.loads(r['body']),id=r['id'],route_id=r['route_id'],effective_from=r['effective_from']) for r in c.execute('select * from tariffs order by effective_from')]
    for kind in ('coverage','card_bindings','expenses'):
        query='select * from '+kind+(' where deleted=0' if kind!='coverage' else '')
        d[kind]=[resolve_row(dict(json.loads(r['body']),id=r['id'],revision=r['revision']),cats) for r in c.execute(query)]
    if c.execute("select 1 from sqlite_master where name='transtrade_orders'").fetchone():
        raw={r['id']:json.loads(r['body']) for r in c.execute('select id,body from transtrade_orders')}
        from app.transtrade import normalize
        for trip in d['trips']:
            if trip.get('origin')=='manual' and trip['id'] in raw:
                trip['api_conflict']=normalize(raw[trip['id']])
    d['meta']['counts']={k:len(d[k]) for k in ('trips','plans','statuses','satellite','routes')}
    return d

def save_catalog(c,kind,b,ident=None):
    body(b)
    if kind not in KINDS:raise ValueError('Неизвестный справочник.')
    cats=catalogs(c);old=next((r for r in cats[kind] if r['id']==ident),None)
    if ident and not old:raise ValueError('Запись не найдена.')
    if old and old.get('merged_into'):raise ValueError('Запись объединена; редактируйте основную запись.')
    if old and b.get('revision')!=old['revision']:raise ValueError('Запись изменена другим пользователем. Обновите страницу.')
    name=str(b.get('name','')).strip()
    if not name or len(name)>200:raise ValueError('Название обязательно, до 200 символов.')
    aliases=b.get('aliases',old.get('aliases',[]) if old else [])
    if not isinstance(aliases,list) or any(not isinstance(x,str) or not x.strip() or len(x)>200 for x in aliases):raise ValueError('Некорректные варианты названия.')
    aliases=list(dict.fromkeys(x.strip() for x in aliases))
    if old and name!=old['name']:aliases=list(dict.fromkeys([*aliases,old['name']]))
    for other in cats[kind]:
        if other['id']!=ident and set([name,*aliases]) & set([other['name'],*other.get('aliases',[])]):
            raise ValueError('Такое название уже существует. Для одного объекта используйте объединение записей.')
    result=dict(name=name,aliases=aliases,archived=bool(b.get('archived',False)))
    if kind=='vehicles':
        result.update(brand=str(b.get('brand','')).strip(),company=str(b.get('company','')).strip(),resource_type=b.get('resource_type','vehicle'))
        if result['resource_type'] not in ('vehicle','partner','placeholder','service'):raise ValueError('Укажите тип ресурса.')
        if result['resource_type']=='vehicle':
            from app.importer import vehicle
            normalized=vehicle(name)
            if not re.fullmatch(r'[А-Я]\d{3}[А-Я]{2}\d{2,3}',normalized):raise ValueError('Укажите полный госномер автомобиля.')
            result['name']=normalized
            if any(other['id']!=ident and normalized in [other['name'],*other.get('aliases',[])] for other in cats[kind]):raise ValueError('Госномер уже существует.')
    if kind=='drivers':result.update(company=str(b.get('company','')).strip(),partner=bool(b.get('partner',False)),placeholder=name.casefold() in PLACEHOLDERS)
    if kind=='routes':result.update(group=str(b.get('group','')).strip(),inactive_route=bool(b.get('inactive_route',False)))
    for field in ('company',):
        if result.get(field) and not lookup(cats,'companies',result[field],True):raise ValueError('Сначала добавьте компанию в справочник.')
    ident=ident or str(uuid.uuid4())
    if old:c.execute('update catalog set body=?,revision=revision+1 where id=?',(dump(result),ident))
    else:c.execute('insert into catalog(id,kind,body) values(?,?,?)',(ident,kind,dump(result)))
    return ident

def merge_catalog(c,kind,source,target):
    if kind not in ('drivers','vehicles'):raise ValueError('Объединять можно машины и водителей.')
    cats=catalogs(c);a=lookup(cats,kind,source);b=lookup(cats,kind,target,True)
    if not a or not b or a['id']==b['id']:raise ValueError('Выберите две разные записи.')
    a.update(merged_into=b['id'],archived=True)
    c.execute('update catalog set body=?,revision=revision+1 where id=?',(dump({k:v for k,v in a.items() if k not in ('id','revision')}),a['id']))

def save_tariff(c,b):
    body(b)
    route=lookup(catalogs(c),'routes',b.get('route_id'),True)
    if not route:raise ValueError('Выберите активный маршрут.')
    effective=iso(b.get('effective_from'))
    values={k:numeric(b.get(k),nullable=k in ('hours','rate','partner_rate')) for k in NUMBERS}
    ident=uid('rate',route['id'],effective)
    if c.execute('select 1 from tariffs where id=?',(ident,)).fetchone():raise ValueError('На эту дату тариф уже существует. Исторические тарифы неизменяемы; добавьте новую дату.')
    c.execute('insert into tariffs values(?,?,?,?)',(ident,route['id'],effective,dump(values)))
    return ident

def can_edit(u,r,kind):
    if u['role']=='admin':return True
    if u['role']!='logist':return False
    return r.get('vehicle') in u['vehicles'] if kind in ('plans','trips') else r.get('kind')=='vehicle' and r.get('entity') in u['vehicles']

def prepare_record(c,kind,b,u,old=None):
    cats=catalogs(c);day=iso(b.get('date'));r=dict(date=day,origin='manual',source='Введено в приложении',created_by=u['id'],note=str(b.get('note',''))[:1000])
    if kind=='trips':
        ident=str(b.get('id','')).strip()
        if not ident or len(ident)>100:raise ValueError('Укажите номер заявки.')
        try:
            start=dt.datetime.fromisoformat(str(b.get('start')));end=dt.datetime.fromisoformat(str(b.get('end')))
            duration=(end-start).total_seconds()/3600
        except (ValueError,TypeError):raise ValueError('Укажите начало и окончание заявки.') from None
        if start.tzinfo or end.tzinfo or duration<0:raise ValueError('Проверьте время заявки: используются местные даты без часового пояса.')
        r.update(id=ident,start=start.isoformat(),end=end.isoformat(),date=start.date().isoformat(),hours=duration,category=b.get('category','Рейс'))
        if r['category'] not in ('Рейс','Удержание','Доплата','Погрузка','Сервис','Корректировка'):raise ValueError('Выберите категорию.')
        for field,catkind in REFS.items():
            if field=='route':continue
            ref=lookup(cats,catkind,b.get(field+'_id') or b.get(field),True)
            r[field]=ref['name'] if ref else '';r[field+'_id']=ref['id'] if ref else None
        if r['category']=='Рейс' and (not r['vehicle'] or not r['driver']):raise ValueError('Для рейса нужны машина и водитель.')
        if u['role']!='admin' and r['vehicle'] not in u['vehicles']:raise PermissionError()
        for k in ('revenue','payout'):
            try:v=float(b.get(k))
            except (ValueError,TypeError):raise ValueError('Введите сумму.') from None
            if not math.isfinite(v):raise ValueError('Сумма должна быть конечным числом.')
            r[k]=v
        r['km']=numeric(b.get('km'));r['user_edited']=True
    elif kind=='plans':
        state=b.get('state','scheduled')
        if state not in STATES:raise ValueError('Неизвестное состояние плана.')
        route=lookup(cats,'routes',b.get('route_id') or b.get('route'),True)
        car=lookup(cats,'vehicles',b.get('vehicle_id') or b.get('vehicle'),True)
        driver=lookup(cats,'drivers',b.get('driver_id') or b.get('driver'),True)
        if not route:raise ValueError('Выберите активный маршрут.')
        if state=='scheduled' and (not car or not driver or car.get('resource_type') in ('placeholder','service') or driver.get('placeholder')):raise ValueError('Для назначенного рейса нужны автомобиль/партнёр и водитель.')
        if route.get('inactive_route') and state=='scheduled':raise ValueError('Маршрут отмечен как не выполняющийся. Измените состояние.')
        if u['role']!='admin' and (not car or car['name'] not in u['vehicles']):raise PermissionError()
        partner=bool(driver and driver.get('partner'))
        r.update(vehicle=car['name'] if car else '',vehicle_id=car['id'] if car else None,driver=driver['name'] if driver else '',driver_id=driver['id'] if driver else None,
                 route=route['name'],route_id=route['id'],partner=partner,state=state,slot=str(b.get('slot','')).strip()[:100])
        same=old and all(old.get(k)==r.get(k) for k in ('date','route_id','driver_id','partner'))
        if same:
            r.update({k:old.get(k) for k in ('revenue','payout','km','hours','tariff_id')})
        else:
            rate=current_rate(c,route['id'],day)
            r.update(revenue=rate['revenue'],payout=rate['partner_payout'] if partner else rate['payout'],km=rate['km'],hours=rate['hours'],tariff_id=rate['tariff_id'])
    elif kind=='statuses':
        entity_kind=b.get('kind')
        if entity_kind not in ('vehicle','driver'):raise ValueError('Выберите вид объекта.')
        entity=lookup(cats,entity_kind+'s',b.get('entity_id') or b.get('entity'),True)
        why=lookup(cats,'reasons',reason(b.get('reason')),True)
        if not entity or not why:raise ValueError('Выберите объект и причину из справочников.')
        r.update(kind=entity_kind,entity=entity['name'],entity_id=entity['id'],reason=why['name'])
        if u['role']!='admin':
            allowed=entity_kind=='vehicle' and entity['name'] in u['vehicles']
            if entity_kind=='driver':
                d=dataset(c);allowed=any(x.get('driver_id')==entity['id'] and x.get('vehicle') in u['vehicles'] for x in d['plans']+d['trips'])
            if not allowed:raise PermissionError()
    else:raise ValueError('Неизвестный вид записи.')
    return r

def create_records(c,kind,b,u):
    body(b)
    if kind not in ('plans','statuses','trips'):raise ValueError('Неизвестный вид записи.')
    if kind=='trips':b=dict(b,date=str(b.get('start',''))[:10],end_date=str(b.get('start',''))[:10])
    a=dt.date.fromisoformat(iso(b.get('date')));z=dt.date.fromisoformat(iso(b.get('end_date',b.get('date'))))
    if not 0<=(z-a).days<=366:raise ValueError('Период должен быть от 1 до 367 дней.')
    weekdays=b.get('weekdays',list(range(7)))
    if not isinstance(weekdays,list) or any(type(x)!=int or not 0<=x<=6 for x in weekdays):raise ValueError('Некорректные дни недели.')
    if not weekdays:raise ValueError('Выберите хотя бы один день недели.')
    existing={natural(kind,r):r for r in dataset(c)[kind]}
    created=0
    for i in range((z-a).days+1):
        day=a+dt.timedelta(days=i)
        if day.weekday() not in weekdays:continue
        r=prepare_record(c,kind,dict(b,date=day.isoformat()),u);key=natural(kind,r)
        if key in existing:continue
        ident=uid('manual-'+kind,key)
        c.execute('insert into records(id,kind,body) values(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,deleted=0,revision=records.revision+1',(ident,kind,dump(r)))
        existing[key]=r;created+=1
    return created

def edit_record(c,ident,b,u,delete=False):
    body(b)
    old=c.execute('select * from records where id=? and deleted=0',(ident,)).fetchone()
    if not old or old['kind'] not in ('plans','statuses','trips'):raise ValueError('Запись не найдена.')
    row=resolve_row(json.loads(old['body']),catalogs(c));kind=old['kind']
    if kind=='trips' and row.get('origin')!='manual':
        if u['role']!='admin':raise PermissionError()
        if delete:raise ValueError('Исходная заявка не удаляется из приложения.')
        category=b.get('category')
        if category not in ('Рейс','Удержание','Доплата','Погрузка','Сервис','Корректировка'):raise ValueError('Выберите категорию.')
        row.setdefault('original_category',row['category'])
        row.update(category=category,category_override=category)
    else:
        allowed=can_edit(u,row,kind)
        if kind=='statuses' and row.get('kind')=='driver' and u['role']=='logist':
            d=dataset(c);allowed=any(r.get('driver_id')==row.get('entity_id') and r.get('vehicle') in u['vehicles'] for r in d['trips']+d['plans'])
        if not allowed:raise PermissionError()
        if delete:
            if kind=='statuses':
                for x in dataset(c)['statuses']:
                    if x['id']==ident:
                        for related in x.get('related_ids',[]):c.execute('update records set deleted=1,revision=revision+1 where id=?',(related,))
            c.execute('update records set deleted=1,revision=revision+1 where id=?',(ident,));return
        previous=row
        row=prepare_record(c,kind,b,u,row);row['user_edited']=True
        for key in ('origin','source','source_id','created_by'):row[key]=previous.get(key,row.get(key))
        for other in dataset(c)[kind]:
            if other['record_id']!=ident and natural(kind,other)==natural(kind,row) and row.get('state')!='cancelled':raise ValueError('Такое назначение/статус уже есть. Для отдельного рейса укажите номер смены.')
    if b.get('revision')!=old['revision']:raise ValueError('Запись изменена другим пользователем. Обновите страницу.')
    c.execute('update records set body=?,revision=revision+1 where id=?',(dump(row),ident))

def save_extra(c,kind,b,u,ident=None):
    body(b)
    if kind not in ('coverage','card_bindings','expenses'):raise ValueError('Неизвестная таблица.')
    if u['role']!='admin':raise PermissionError()
    old=c.execute('select * from '+kind+' where id=?',(ident,)).fetchone() if ident else None
    if ident and (not old or b.get('revision')!=old['revision']):raise ValueError('Запись изменена или не найдена. Обновите страницу.')
    cats=catalogs(c);r={'note':str(b.get('note',''))[:1000]}
    if kind in ('coverage','card_bindings'):
        r.update(start=iso(b.get('start')),end=iso(b.get('end')))
        if r['start']>r['end']:raise ValueError('Конец периода раньше начала.')
    if kind=='coverage':
        if b.get('source') not in ('trips','plans'):raise ValueError('Выберите источник: заявки или план.')
        r.update(source=b['source'],complete=bool(b.get('complete')),scope='all')
    else:
        car=lookup(cats,'vehicles',b.get('vehicle_id') or b.get('vehicle'),True)
        if not car or car.get('resource_type')!='vehicle':raise ValueError('Выберите автомобиль.')
        r.update(vehicle_id=car['id'],vehicle=car['name'])
        if kind=='card_bindings':
            if b.get('provider') not in ('neftm','rosneft'):raise ValueError('Выберите провайдера карты.')
            card=str(b.get('card','')).strip()
            if not card or len(card)>100:raise ValueError('Укажите номер карты.')
            r.update(provider=b['provider'],card=card)
            for other in c.execute('select * from card_bindings where deleted=0'):
                x=json.loads(other['body'])
                if other['id']!=ident and x['provider']==r['provider'] and x['card']==card and x['start']<=r['end'] and r['start']<=x['end']:raise ValueError('Период привязки этой карты пересекается с существующим.')
        else:
            r.update(date=iso(b.get('date')),category=str(b.get('category','')).strip(),amount=numeric(b.get('amount')))
            if not r['category']:raise ValueError('Укажите вид расхода.')
    ident=ident or str(uuid.uuid4())
    if old:c.execute('update '+kind+' set body=?,revision=revision+1 where id=?',(dump(r),ident))
    else:c.execute('insert into '+kind+'(id,body) values(?,?)',(ident,dump(r)))
    return ident
