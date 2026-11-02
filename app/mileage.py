"""Verified TT mileage observations. Never rewrite provider orders or infer distance."""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import zipfile
from app.importer import vehicle

class Conflict(ValueError):
    pass

def dump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(v):
    return hashlib.sha256(dump(v).encode()).hexdigest()

def instant(v):
    try:
        d = dt.datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        if d.tzinfo is None: raise ValueError()
        return d.astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        raise ValueError('Укажите время источника с часовым поясом, например 2026-11-02T11:00:00+03:00.') from None

def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS mileage_observations(provider_id TEXT,revision INTEGER,body TEXT NOT NULL,PRIMARY KEY(provider_id,revision))')

def current(c):
    if not c.execute("select 1 from sqlite_master where name='mileage_observations'").fetchone(): return {}
    return {r[0]: dict(json.loads(r[2]), revision=r[1]) for r in c.execute('SELECT provider_id,revision,body FROM mileage_observations WHERE (provider_id,revision) IN (SELECT provider_id,max(revision) FROM mileage_observations GROUP BY provider_id)')}

def identity(row):
    return digest({k: row.get(k) for k in ('provider_id','number','date','start','end','vehicle_id','driver_id','client_id','cancelled')})

def trips(c):
    from app import workspace as ws
    cats=ws.catalogs(c)
    return [ws.resolve_row(json.loads(r[0]),cats) for r in c.execute("select body from records where kind='trips' and deleted=0") if json.loads(r[0]).get('origin')=='transtrade']

def parse(content, filename):
    if len(content)>8*1024*1024: raise ValueError('Размер отчета ограничен 8 МБ.')
    if filename.lower().endswith('.xlsx'):
        from openpyxl import load_workbook
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if sum(x.file_size for x in z.infolist())>40*1024*1024: raise ValueError('Слишком большая распакованная книга.')
            book=load_workbook(io.BytesIO(content),read_only=True,data_only=True)
            iterator=book.active.iter_rows(values_only=True)
            headers=[str(x or '').strip() for x in next(iterator)]
            rows=[]
            for n,row in enumerate(iterator,2):
                if n>10001: raise ValueError('Не более 10000 строк в одном отчете.')
                if any(v is not None for v in row): rows.append(dict(zip(headers,row),_row=n))
            book.close()
        except (zipfile.BadZipFile,StopIteration,KeyError): raise ValueError('Не удалось прочитать XLSX.') from None
    elif filename.lower().endswith('.csv'):
        try:
            text=content.decode('utf-8-sig'); delimiter=';' if ';' in text.splitlines()[0] else ','
            reader=csv.DictReader(io.StringIO(text),delimiter=delimiter)
            headers=reader.fieldnames or []
            rows=[dict(r,_row=n) for n,r in enumerate(reader,2)]
        except (UnicodeError,IndexError,csv.Error): raise ValueError('Ожидается CSV UTF-8 с заголовками.') from None
        if len(rows)>10000: raise ValueError('Не более 10000 строк в одном отчете.')
    else: raise ValueError('Выберите CSV UTF-8 или XLSX.')
    if not {'date','vehicle','km'}.issubset(headers) or not ({'provider_id','number'} & set(headers)):
        raise ValueError('Нужны столбцы provider_id или number, date, vehicle, km. Единицы km — километры.')
    if len(set(headers))!=len(headers): raise ValueError('Заголовки столбцов повторяются.')
    return rows

def preview(c,content,filename,source_as_of,source_ref):
    asof=instant(source_as_of)
    if dt.datetime.fromisoformat(asof)>dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=5): raise ValueError('Дата источника не может быть в будущем.')
    ref=str(source_ref or '').strip()
    if not ref or len(ref)>500: raise ValueError('Укажите основание: отчет или документ ТТ, до 500 символов.')
    rows=parse(content,filename); candidates=trips(c); existing=current(c); result=[]; seen=set()
    sha=hashlib.sha256(content).hexdigest()
    for row in rows:
        out={'row':row['_row'],'number':str(row.get('number') or ''),'provider_id':str(row.get('provider_id') or ''),'status':'invalid'}
        try:
            raw=row.get('km')
            if raw is None or str(raw).strip()=='': raise ValueError('Километраж не указан; пустое значение не равно нулю.')
            if isinstance(raw,bool): raise ValueError('Некорректный километраж.')
            km=float(str(raw).replace(',','.'))
            if not math.isfinite(km) or km<0: raise ValueError('Километраж должен быть конечным и неотрицательным.')
            date=row.get('date'); date=date.date().isoformat() if isinstance(date,dt.datetime) else dt.date.fromisoformat(str(date)).isoformat()
            plate=vehicle(row.get('vehicle'))
            if not plate: raise ValueError('Укажите автомобиль для проверки соответствия.')
            ident=out['provider_id']
            matched=[t for t in candidates if (str(t.get('provider_id'))==ident if ident else out['number'] and str(t.get('number'))==out['number'])]
            matched=[t for t in matched if t.get('date')==date and vehicle(t.get('vehicle'))==plate]
            if len(matched)!=1: raise ValueError('Не найдено единственное соответствие ID/номера, даты и автомобиля.')
            t=matched[0]; ident=str(t['provider_id'])
            if out['number'] and out['number']!=str(t.get('number')): raise ValueError('Номер не соответствует API ID.')
            if ident in seen: raise ValueError('Один API ID повторяется в файле; исправьте пакет.')
            seen.add(ident)
            if t.get('cancelled'): raise ValueError('Заявка отменена; требуется проверка.')
            out.update(provider_id=ident,number=t.get('number'),km=km,date=date,vehicle=plate,identity=identity(t),status='ready')
            old=existing.get(ident)
            if old:
                if asof<old['source_as_of']: out.update(status='older',reason='Есть более свежий источник.')
                elif asof==old['source_as_of']:
                    out.update(status='unchanged' if km==old['km'] and out['identity']==old['identity'] else 'conflict',reason='Та же дата источника: повтор или конфликт значений.')
            out['previous_revision']=old['revision'] if old else 0
        except (ValueError,TypeError) as e:
            out['reason']=str(e) if isinstance(e,ValueError) else 'Некорректное значение.'
        result.append(out)
    payload={'sha256':sha,'source_as_of':asof,'source_ref':ref,'rows':result}
    return dict(payload,token=digest(payload),ready=sum(r['status']=='ready' for r in result))

def apply(c,content,filename,source_as_of,source_ref,token,user_id):
    # Caller takes BEGIN IMMEDIATE, so matching, CAS preview and insert are one transaction.
    result=preview(c,content,filename,source_as_of,source_ref)
    if not token or token!=result['token']: raise Conflict('Заявки или дополнения изменились. Повторите предварительную проверку.')
    if any(r['status'] in ('invalid','conflict') for r in result['rows']): raise ValueError('Исправьте конфликтующие строки перед подтверждением пакета.')
    now=dt.datetime.now(dt.timezone.utc).isoformat(); count=0
    for row in result['rows']:
        if row['status']!='ready': continue
        observation={k:row[k] for k in ('provider_id','number','date','vehicle','km','identity')}
        observation.update(source_type='verified_tt_export',source_as_of=result['source_as_of'],source_ref=result['source_ref'],sha256=result['sha256'],source_row=row['row'],confirmed_by=user_id,confirmed_at=now,unit='km')
        c.execute('INSERT INTO mileage_observations VALUES(?,?,?)',(row['provider_id'],row['previous_revision']+1,dump(observation)));count+=1
    return {'applied':count,'unchanged':sum(r['status']=='unchanged' for r in result['rows']),'older':sum(r['status']=='older' for r in result['rows'])}

def enrich(c,rows):
    observations=current(c)
    for row in rows:
        if row.get('origin')!='transtrade': continue
        observation=observations.get(str(row.get('provider_id')))
        if not observation: continue
        valid=identity(row)==observation['identity'] and not row.get('cancelled')
        row['km_observation']=dict(observation,status='verified' if valid else 'stale',reason='' if valid else 'Реквизиты заявки изменились после сверки. Нужен новый отчет ТТ.')
        if valid:
            # Current API has no verified mileage contract. A future API mapper must resolve precedence explicitly.
            row['km']=observation['km'];row.setdefault('sources',{})['km']='Подтвержденный отчет ТТ · '+observation['source_as_of']
        else: row['km']=None
    return rows
