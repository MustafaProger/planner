"""Read-only Excel import. All financial source values retained without inferred tax rules."""
import collections, datetime as dt, hashlib, json, re, warnings
from pathlib import Path
import openpyxl
warnings.filterwarnings('ignore',category=UserWarning,module='openpyxl')
SOURCE=Path('/Users/mustafa/Desktop/проект')
def text(v): return str(v).strip() if v is not None else ''
def number(v):
    if v is None or v=='': return 0.0
    return float(v)
def hours(v):
    if v is None:return None
    if isinstance(v,dt.timedelta):return v.total_seconds()/3600
    if isinstance(v,dt.time):return v.hour+v.minute/60+v.second/3600
    if isinstance(v,(float,int)):return v*24
    parts=str(v).split(':');return sum(float(x)/60**i for i,x in enumerate(parts))
def date(v):
    if isinstance(v,dt.datetime):return v
    if isinstance(v,dt.date):return dt.datetime.combine(v,dt.time())
    for fmt in ['%d.%m.%Y %H:%M:%S','%Y-%m-%d %H:%M:%S','%Y-%m-%d','%d.%m.%Y']:
        try:return dt.datetime.strptime(str(v),fmt)
        except ValueError:pass
    raise ValueError('Некорректная дата в исходных данных')
def vehicle(v):
    s=text(v).upper().replace(' ','')
    if re.fullmatch(r'[A-ZА-Я]\d{3}[A-ZА-Я]{2}\d{2,3}',s):
        return s.translate(str.maketrans('ABEKMHOPCTYX','АВЕКМНОРСТУХ'))
    return text(v)
def load_excel(stat_path=None,plan_path=None):
    stat_path=Path(stat_path or SOURCE/'Статистика 17.09.2026.xlsx');plan_path=Path(plan_path or SOURCE/'Планировщик ЛОГИСТИКА АА (Р4).xlsx')
    sw=openpyxl.load_workbook(stat_path,data_only=True);pw=openpyxl.load_workbook(plan_path,data_only=True)
    required={'ТрансТрейд','Спутник','Блокнот','Справочник'}
    if not required.issubset(sw.sheetnames) or not {'Логист','Маршруты Почта','Водители','Автомобили'}.issubset(pw.sheetnames):raise ValueError('Не найдены обязательные листы исходных книг')
    trips=[];statuses={};sat=[];routes=[];plans=[];issues=[];vehicles={};drivers={}
    def status(day,kind,entity,reason,source):
        if entity and reason:
            key=(day,kind,entity,reason)
            if key in statuses: statuses[key]['source']+='; '+source
            else: statuses[key]=dict(date=day,kind=kind,entity=entity,reason=reason,source=source)
    for r in list(sw['Справочник'].values)[1:]:
        if r[0]:vehicles[vehicle(r[0])]=text(r[1])
        if text(r[3]):drivers[text(r[3])]=''
    mapping={text(r[9]):vehicle(r[10]) for r in list(sw['Справочник'].values)[1:] if r[9] and r[10]}
    reasons={text(r[5]) for r in list(sw['Справочник'].values)[1:] if r[5]}
    for row,r in enumerate(list(sw['ТрансТрейд'].values)[2:],3):
        if not any(v is not None for v in r):continue
        start=date(r[1]);end=date(r[2]);day=start.date().isoformat();car=vehicle(r[7]);driver=text(r[5]);client=text(r[3]);typ=text(r[6]);src=f'ТрансТрейд!{row}'
        if r[0] is None and client in reasons:
            status(day,'vehicle',car,client,src);continue
        if r[0] is None:issues.append(f'{src}: строка без номера заказа');continue
        h=(end-start).total_seconds()/3600
        if h<0:issues.append(f'{src}: окончание раньше начала');h=None
        if not car:issues.append(f'{src}: отсутствует автомобиль; сумма сохранена в группе «Не указано»')
        if h is not None and h>24:issues.append(f'{src}: длительность больше 24 часов; сохранена исходная разница дат')
        category='Рейс'
        if any(s in typ.lower() for s in ['штраф','удерж']):category='Удержание'
        elif 'сервис' in typ.lower():category='Сервис'
        elif 'погруз' in typ.lower():category='Погрузка'
        elif 'доплата' in typ.lower():category='Доплата'
        trips.append(dict(id=str(r[0]),date=day,start=start.isoformat(),end=end.isoformat(),client=client,carrier=text(r[4]),driver=driver,type=typ,vehicle=car,revenue=number(r[8]),payment=text(r[9]),payout=number(r[10]),payout_method=text(r[11]),km=number(r[12]),hours=h,category=category,source=src))
        if car:vehicles.setdefault(car,'')
        if driver:drivers.setdefault(driver,'')
    for row,r in enumerate(list(sw['Блокнот'].values)[7:],8):
        if not isinstance(r[0],(dt.date,dt.datetime)):continue
        day=date(r[0]).date().isoformat();status(day,'vehicle',vehicle(r[1]),text(r[2]),f'Блокнот!{row}');status(day,'driver',text(r[3]),text(r[4]),f'Блокнот!{row}')
    for row,r in enumerate(list(sw['Спутник'].values)[1:],2):
        if not r[1]:continue
        obj=text(r[1]);car=mapping.get(obj)
        if not car:
            match=re.search(r'[А-Яа-яA-Za-z]\d{3}[А-Яа-яA-Za-z]{2}\d{2,3}',obj)
            car=vehicle(match.group()) if match else ''
            issues.append(f'Спутник!{row}: объект сопоставлен по номеру' if car else f'Спутник!{row}: неизвестный объект {obj}')
        sat.append(dict(date=date(r[2]).date().isoformat(),vehicle=car,object=obj,start=date(r[2]).isoformat(),end=date(r[3]).isoformat(),hours=hours(r[4]),km=number(r[5]),engine_hours=hours(r[8]),movement_hours=hours(r[9]),stop_hours=hours(r[10]),source=f'Спутник!{row}'))
    for r in list(pw['Водители'].values)[1:]:
        if text(r[0]):drivers[text(r[0])]=text(r[1])
    for r in list(pw['Автомобили'].values)[1:]:
        if r[0]:vehicles[vehicle(r[0])]=text(r[1])
    for row,r in enumerate(list(pw['Маршруты Почта'].values)[1:],2):
        if not r[1]:continue
        routes.append(dict(id=text(r[1]),group=text(r[0]),revenue=number(r[2]),payout=number(r[3]),partner_payout=number(r[4]),km=number(r[5]),hours=hours(r[6]),rate=number(r[7]),partner_rate=number(r[8]),source=f'Маршруты Почта!{row}'))
    route_map={r['id']:r for r in routes}
    for row,r in enumerate(list(pw['Логист'].values)[6:],7):
        if not r[0]:continue
        route=route_map.get(text(r[4]));driver=text(r[2]);car=vehicle(r[3]);partner=drivers.get(driver)=='Партнёр'
        if route is None:issues.append(f'Логист!{row}: маршрут не найден: {text(r[4])}')
        plans.append(dict(id=f'excel:{row}',date=date(r[0]).date().isoformat(),driver=driver,vehicle=car,route=text(r[4]),revenue=route['revenue'] if route else None,payout=(route['partner_payout'] if partner else route['payout']) if route else None,km=route['km'] if route else None,hours=route['hours'] if route else None,partner=partner,source=f'Логист!{row}'))
    ids=[x['id'] for x in trips]
    if len(set(ids))!=len(ids):raise ValueError('Повторяющиеся номера заявок: импорт остановлен')
    meta=dict(imported_at=dt.datetime.now(dt.timezone.utc).isoformat(),files=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (stat_path,plan_path)],issues=issues,source='Excel-снимок',counts=dict(trips=len(trips),satellite=len(sat),statuses=len(statuses),plans=len(plans),routes=len(routes)))
    return dict(trips=trips,satellite=sat,statuses=list(statuses.values()),routes=routes,plans=plans,vehicles=vehicles,drivers=drivers,meta=meta)
if __name__=='__main__':
    d=load_excel();print(json.dumps(d['meta'],ensure_ascii=False,indent=2))
