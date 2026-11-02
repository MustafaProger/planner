"""Read-only TransTrade GetOrders, transactional upsert and retained source history."""
import datetime as dt
import hashlib
import fcntl
import json
import math
import os
import secrets
import sqlite3
import threading
import socket
import sys
import time
from contextlib import contextmanager
from itertools import islice, zip_longest
from pathlib import Path
import requests
from app import workspace as ws
from app.importer import vehicle

URL = 'https://tt-ok.ru/data/api'
MUTEX = threading.Lock()
MSK = dt.timezone(dt.timedelta(hours=3))
MAX_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_RESPONSE_SECONDS = 120
RECONCILE_INTERVAL = dt.timedelta(hours=24)
RECONCILE_RETRY = dt.timedelta(hours=1)
MAX_ID_CHECKS = 256
MAX_RECONCILE_SECONDS = 240
LIMITATIONS = ('API не передаёт километраж. Время возвращается без часового пояса; '
              'используются календарные даты базы ТТ без сдвига, для интерфейса принят МСК. '
              'Нет документированного счётчика, пагинации и признака удаления. '
              'Даже запрос без фильтров пропускает некоторые доступные по ID заявки. '
              'Известные пропуски и ограниченная очередь промежутков ID проверяются отдельно. '
              'Не найденные даже по ID сохраняются и требуют проверки; полнота факта автоматически не подтверждается.')

def credentials(data_dir):
    try:
        value = json.loads((Path(data_dir)/'transtrade-credentials.json').read_text())
        if value.get('api_url') != URL or not value.get('api_key') or int(value['api_user_id']) <= 0:raise ValueError()
        return value
    except (OSError,ValueError,KeyError,TypeError):
        raise ValueError('Не настроены серверные API-реквизиты ТрансТрейда.') from None

def configured(data_dir):
    try:credentials(data_dir);return True
    except ValueError:return False

def transport(data_dir):
    """Optional per-provider macOS route. TLS verification and host stay unchanged."""
    path=Path(data_dir)/'transtrade-network.json'
    interface=''
    if path.exists():
        try:
            setting=json.loads(path.read_text())
            interface=setting.get('interface','')
            if not isinstance(interface,str) or not interface or len(interface)>32:raise ValueError()
        except (OSError,ValueError,AttributeError):raise ValueError('Некорректная сетевая настройка ТрансТрейда.') from None
    http=requests.Session()
    if interface:
        if sys.platform!='darwin':
            http.close();raise ValueError('Выбранный сетевой интерфейс ТТ поддерживается только на macOS.')
        try:index=socket.if_nametoindex(interface)
        except OSError:
            http.close();raise ValueError('Сетевой интерфейс ТТ недоступен. Проверьте подключение компьютера.') from None
        from requests.adapters import HTTPAdapter
        from urllib3.connection import HTTPConnection
        class InterfaceAdapter(HTTPAdapter):
            def init_poolmanager(self,*args,**kwargs):
                # macOS SDK netinet/in.h: IP_BOUND_IF = 25.
                kwargs['socket_options']=HTTPConnection.default_socket_options+[(socket.IPPROTO_IP,25,index)]
                return super().init_poolmanager(*args,**kwargs)
        http.mount('https://tt-ok.ru/',InterfaceAdapter())
    return http

def omitted_ids(c,start,end,seen):
    result=set()
    for x in c.execute("select body from records where kind='trips' and deleted=0"):
        r=json.loads(x[0]);ident=str(r['id'])
        if r.get('origin') in ('excel','transtrade') and start<=r['date']<=end and ident.isdigit() and ident not in seen:
            result.add(ident)
    return sorted(result,key=int)

def get_orders(config, params):
    data=json.dumps(dict(params,api_user_id=int(config['api_user_id'])),ensure_ascii=False,separators=(',',':'))
    nonce=secrets.token_hex(16);method='GetOrders'
    signature=hashlib.md5('###'.join([config['api_key'],data,method,nonce,config['api_key']]).encode()).hexdigest()
    for attempt in range(2):
        response=None
        started=time.monotonic()
        try:
            response=config.get('_session',requests).post(URL,data=dict(data=data,method=method,random=nonce,signature=signature),timeout=(15,45),allow_redirects=False,stream=True)
            if response.status_code!=200:raise ValueError(f'ТрансТрейд: HTTP {response.status_code}. Прежние заявки сохранены.')
            body=bytearray()
            for chunk in response.iter_content(64*1024):
                if len(body)+len(chunk)>MAX_RESPONSE_BYTES:
                    raise ValueError('ТрансТрейд: ответ превышает лимит 128 МиБ. Прежние заявки сохранены; требуется пересмотр способа выгрузки.')
                if time.monotonic()-started>MAX_RESPONSE_SECONDS:
                    raise ValueError('ТрансТрейд: превышено время загрузки ответа. Прежние заявки сохранены.')
                body.extend(chunk)
            break
        except requests.Timeout:
            if attempt:raise ValueError('ТрансТрейд: тайм-аут соединения или ответа после двух попыток. Прежние заявки сохранены.') from None
        except requests.RequestException:raise ValueError('ТрансТрейд: ошибка сети / TLS. Прежние заявки сохранены.') from None
        finally:
            if response is not None:response.close()
    try:payload=json.loads(body)
    except ValueError:raise ValueError('ТрансТрейд вернул не JSON. Прежние заявки сохранены.') from None
    if not isinstance(payload,dict) or payload.get('error_code') not in (0,'0'):
        # Provider text is untrusted and can echo request secrets. Do not log/return it.
        raise ValueError('ТрансТрейд отклонил GetOrders (error_code != 0). Проверьте API-доступ у владельца базы.')
    rows=payload.get('data')
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError('ТрансТрейд: некорректный список заявок.')
    config['_response_meta']=dict(response_bytes=len(body),seconds=round(time.monotonic()-started,3))
    return rows

def amount(value):
    if value in (None,''):return None
    if isinstance(value,bool):raise ValueError('ТрансТрейд: некорректная сумма.')
    try:n=float(str(value).replace(',','.'))
    except ValueError:raise ValueError('ТрансТрейд: некорректная сумма.') from None
    if not math.isfinite(n):raise ValueError('ТрансТрейд: неконечная сумма.')
    return n

def timestamp(value, required=False):
    if not value and not required:return ''
    try:
        parsed=dt.datetime.strptime(str(value),'%Y-%m-%d %H:%M:%S')
        return parsed.isoformat()
    except ValueError:raise ValueError('ТрансТрейд: отсутствует или некорректна дата заявки. Загрузка не применена.') from None

def normalize(raw):
    ident=str(raw.get('ID',''))
    if not ident.isdigit() or int(ident)<=0:raise ValueError('ТрансТрейд: отсутствует постоянный ID заявки.')
    ident=str(int(ident))
    start=timestamp(raw.get('BeginDateTime'),True);end=timestamp(raw.get('EndDateTime'))
    duration=(dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(start)).total_seconds()/3600 if end else None
    if duration is not None and duration<0:duration=None
    typ=str(raw.get('AutoType') or '');category='Рейс'
    if any(x in typ.lower() for x in ('штраф','удерж')):category='Удержание'
    elif 'сервис' in typ.lower():category='Сервис'
    elif 'погруз' in typ.lower():category='Погрузка'
    elif 'доплата' in typ.lower():category='Доплата'
    status=str(raw.get('Status') or '')
    cancelled=status.casefold().strip().startswith(('отмен','аннулиров'))
    r=dict(id=ident,provider_id=ident,number=str(raw.get('Number') or ''),date=start[:10],start=start,end=end,
           vehicle=vehicle(raw.get('TransportNumber')),category='Отмена' if cancelled else category,revenue=amount(raw.get('ClientSum')),
           payout=amount(raw.get('WorkerSum')),km=None,hours=duration,provider_status=status,cancelled=cancelled,
           source='ТрансТрейд API',origin='transtrade',sources={k:'ТрансТрейд API' for k in ('revenue','payout','hours')},
           timezone='Время базы ТТ (без смещения в API)',source_id=ident,created_by=None)
    for key,field in dict(client='Client',driver='Driver',carrier='Worker',type='AutoType',payment='ClientPayType',
                          payout_method='WorkerPayType',load_address='Load',unload_address='Unload',logist='User',
                          firm='Firm',cargo='Cargo',notes='Notes').items():r[key]=str(raw.get(field) or '')
    r['financial_source']={k:amount(raw.get(k)) for k in ('ClientPaidSum','DispSum','BonusSum','ProfitSum')}
    return r

def schema(c):
    # execute, not executescript: must not commit the caller's transaction.
    c.execute('CREATE TABLE IF NOT EXISTS transtrade_orders(id TEXT PRIMARY KEY,body TEXT NOT NULL,seen_at TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS transtrade_history(id TEXT,hash TEXT,body TEXT NOT NULL,at TEXT NOT NULL,PRIMARY KEY(id,hash))')

def status(c):
    row=c.execute("select body from workspace_meta where key='transtrade_status'").fetchone()
    return json.loads(row[0]) if row else None

def save_status(c,value):c.execute("insert or replace into workspace_meta values('transtrade_status',?)",(ws.dump(value),))

def apply(c, raw_rows, start, end, recovered=None, *, full=False, checked_missing=None):
    recovered=recovered or []
    normalized=[normalize(r) for r in raw_rows]
    normalized_ids={r['id'] for r in normalized}
    if len(normalized_ids)!=len(normalized):raise ValueError('Повтор ID в ответе ТрансТрейда; загрузка не применена.')
    if not full and any(not start<=r['date']<=end for r in normalized):raise ValueError('ТрансТрейд вернул записи вне запрошенного периода.')
    # Direct-ID responses may reveal a moved date. Only recover known local IDs
    # missing from this period; unrelated rows and IDs cannot enter this path.
    known=set(omitted_ids(c,start,end,normalized_ids))
    targeted=[normalize(r) for r in recovered]
    if len({r['id'] for r in targeted})!=len(targeted) or any(r['id'] in normalized_ids for r in targeted) or (not full and any(r['id'] not in known for r in targeted)):
        raise ValueError('Некорректный ответ точечного поиска ТрансТрейда; загрузка не применена.')
    for r in targeted:r['api_list_omitted']=True
    raw_rows=[*raw_rows,*recovered];normalized.extend(targeted)
    schema(c);now=dt.datetime.now(MSK).isoformat();stats=dict(received=sum(start<=r['date']<=end for r in normalized),processed=len(normalized),recovered_by_id=len(targeted),moved_out_of_period=sum(not start<=r['date']<=end for r in targeted),created=0,updated=0,unchanged=0,conflicts=0,missing=0)
    ws.seed_catalog(c,dict(trips=normalized,vehicles={r['vehicle']:'' for r in normalized if r['vehicle']},drivers={r['driver']:'' for r in normalized if r['driver']},routes=[],statuses=[]))
    cats=ws.catalogs(c)
    all_records={}
    for x in c.execute("select * from records where kind='trips'"):
        b=json.loads(x['body']);all_records.setdefault(str(b['id']),[]).append((x,b))
    def remember(ident,body):
        digest=hashlib.sha256(body.encode()).hexdigest()
        c.execute('insert or ignore into transtrade_history values(?,?,?,?)',(ident,digest,body,now))
    seen=set();conflict_ids=[];changed_dates=set()
    for raw,r in zip(raw_rows,normalized):
        ident=r['id'];seen.add(ident)
        previous=c.execute('select body from transtrade_orders where id=?',(ident,)).fetchone()
        if previous:remember('api:'+ident,previous[0])
        c.execute('insert or replace into transtrade_orders values(?,?,?)',(ident,ws.dump(raw),now))
        matches=all_records.get(ident,[])
        if len(matches)>1 or any(b.get('origin')=='manual' or b.get('user_edited') or x['deleted'] for x,b in matches):
            stats['conflicts']+=1
            conflict_ids.append(ident)
            continue  # manual data remains authoritative locally; API version retained separately
        r=ws.attach_refs(r,cats)
        if matches:
            x,old=matches[0];rid=x['id']
            if old.get('origin')=='excel':r['legacy_snapshot']=old
            elif old.get('legacy_snapshot'):r['legacy_snapshot']=old['legacy_snapshot']
            if old.get('category_override'):r.update(category='Отмена' if r['cancelled'] else old['category_override'],category_override=old['category_override'],original_category=old.get('original_category',r['category']))
            if ws.dump(r)==ws.dump(old):stats['unchanged']+=1;continue
            changed_dates.update((old['date'],r['date']))
            remember('record:'+rid,x['body'])
            c.execute('update records set body=?,revision=revision+1 where id=?',(ws.dump(r),rid));stats['updated']+=1
        else:
            rid=ws.uid('trips',(ident,),1)
            c.execute("insert into records(id,kind,body) values(?,'trips',?)",(rid,ws.dump(r)));stats['created']+=1
            changed_dates.add(r['date'])
    # No deletion, even on a valid empty response. Mark disappeared rows for review.
    for ident,matches in all_records.items():
        for x,r in matches:
            if ident not in seen and (full or start<=r['date']<=end) and r.get('origin') in ('excel','transtrade') and not x['deleted']:
                if full and checked_missing is not None and ident not in checked_missing:
                    continue  # Pending a direct lookup; absence is not established.
                stats['missing']+=1
                if not r.get('api_missing') and not r.get('user_edited'):
                    remember('record:'+x['id'],x['body']);r['api_missing']=True
                    c.execute('update records set body=?,revision=revision+1 where id=?',(ws.dump(r),x['id']))
                    changed_dates.add(r['date'])
    # Completeness is evaluated against business-content fingerprints on read.
    # A no-op poll must not erase the original attestation.
    result=dict(stats,status='success',start=start,end=end,synced_at=now,limitations=LIMITATIONS,complete=False,conflict_ids=conflict_ids,
                cancelled=sum(r['cancelled'] for r in normalized),without_km=len(normalized),
                without_revenue=sum(r['revenue'] is None for r in normalized),without_payout=sum(r['payout'] is None for r in normalized))
    if full:
        result.update(received=len(normalized),scope='history')
        return result
    previous=c.execute("select body from workspace_meta where key='transtrade_runs'").fetchone()
    runs=json.loads(previous[0]) if previous else []
    runs=[x for x in runs if (x['start'],x['end'])!=(start,end)]+[result]
    c.execute("insert or replace into workspace_meta values('transtrade_runs',?)",(ws.dump(runs),))
    save_status(c,result);return result

class BusyError(ValueError):
    pass


@contextmanager
def sync_lock(data_dir):
    if not MUTEX.acquire(blocking=False):raise BusyError('Загрузка ТрансТрейда уже выполняется.')
    lock_file=None
    try:
        lock_file=(Path(data_dir)/'transtrade.lock').open('a');os.chmod(lock_file.name,0o600)
        try:fcntl.flock(lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise BusyError('Загрузка ТрансТрейда уже выполняется другим процессом.') from None
        yield
    finally:
        if lock_file:lock_file.close()
        MUTEX.release()


def sync(data_dir, db_path, start, end, *, verify_days=True):
    start=ws.iso(start);end=ws.iso(end);a=dt.date.fromisoformat(start);b=dt.date.fromisoformat(end)
    if not 0<=(b-a).days<31:raise ValueError('Выберите период от 1 до 31 дня.')
    with sync_lock(data_dir):
        return _sync(data_dir,db_path,start,end,a,b,verify_days)


def _sync(data_dir,db_path,start,end,a,b,verify_days):
    http=None
    try:
        config=credentials(data_dir);http=transport(data_dir);config['_session']=http;rows=[]
        # Independent day queries constrain undocumented truncation and expose changed responses.
        for offset in range((b-a).days+1 if verify_days else 0):
            day=(a+dt.timedelta(days=offset)).isoformat()
            try:chunk=get_orders(config,dict(FromOrderDate=day,ToOrderDate=day))
            except ValueError as e:raise ValueError(f'Порция {day}: {e}') from None
            if any(normalize(r)['date']!=day for r in chunk):raise ValueError('ТрансТрейд: фильтр даты не соблюдён; загрузка не применена.')
            rows.extend(chunk)
        combined=get_orders(config,dict(FromOrderDate=start,ToOrderDate=end))
        if not verify_days:rows=combined
        by_id=lambda values:{normalize(r)['id']:ws.dump(r) for r in values}
        if len(by_id(rows))!=len(rows) or len(by_id(combined))!=len(combined) or by_id(rows)!=by_id(combined):
            raise ValueError('ТрансТрейд: дневные ответы и ответ за период различаются (изменение данных или неполная выдача). Прежние заявки сохранены; повторите загрузку.')
        with sqlite3.connect(db_path,timeout=30) as c:
            missing=omitted_ids(c,start,end,set(by_id(rows)))
        if len(missing)>100:
            raise ValueError('Более 100 известных заявок отсутствуют в выдаче ТТ. Загрузка не применена; проверьте источник.')
        recovered=[]
        for ident in missing:
            try:found=get_orders(config,dict(OrderId=int(ident)))
            except ValueError as e:raise ValueError(f'Проверка заявки {ident}: {e}') from None
            if len(found)>1 or any(normalize(r)['id']!=ident for r in found):
                raise ValueError('ТрансТрейд вернул неверный ID в точечном поиске. Загрузка не применена.')
            recovered.extend(found)
        with sqlite3.connect(db_path,timeout=30) as c:
            c.row_factory=sqlite3.Row
            c.execute('BEGIN IMMEDIATE')
            result=apply(c,rows,start,end,recovered)

        return result
    except ValueError as e:
        with sqlite3.connect(db_path,timeout=30) as c:
            old=status(c) or {};save_status(c,dict(old,status='error',error=str(e),attempted_at=dt.datetime.now(MSK).isoformat(),attempt_start=start,attempt_end=end,limitations=LIMITATIONS))
        raise
    finally:
        if http:http.close()


def reconciliation_status(c):
    row=c.execute("select body from workspace_meta where key='transtrade_reconciliation'").fetchone()
    return json.loads(row[0]) if row else None


def save_reconciliation(c,value):
    c.execute("insert or replace into workspace_meta values('transtrade_reconciliation',?)",(ws.dump(value),))


def managed_scope(c,previous):
    """Do not import the provider's unrelated decades into the workspace.

    An explicit period import can extend the floor. A known order moved before
    the floor is refreshed by ID without widening the scope to that whole year.
    """
    known=set();dates=[]
    for x in c.execute("select body,deleted from records where kind='trips'"):
        r=json.loads(x[0]);ident=str(r['id'])
        if r.get('origin') in ('excel','transtrade') and ident.isdigit():
            known.add(str(int(ident)))
            if not x[1]:dates.append(r['date'])
    floor=previous.get('scope_start') or min(dates,default=dt.datetime.now(MSK).date().replace(day=1).isoformat())
    row=c.execute("select body from workspace_meta where key='transtrade_runs'").fetchone()
    if row:
        floor=min([floor]+[r['start'] for r in json.loads(row[0])])
    return floor,known


def gap_ranges(ids):
    """Ranges avoid materializing millions of ID holes in a sparse response."""
    numbers=sorted(int(x) for x in ids)
    return [(a+1,b-1) for a,b in zip(numbers,numbers[1:]) if b>a+1]


def rotate_gaps(ranges,cursor):
    # Descending order gives recent unknown orders priority. Persist the next
    # cursor so a large gap set does not starve earlier holes on subsequent days.
    for below in (True,False):
        for low,high in reversed(ranges):
            a,b=(low,min(high,cursor-1)) if below else (max(low,cursor),high)
            yield from range(b,a-1,-1)


def reconcile(data_dir,db_path,*,force=False):
    """Bounded read-only full-list audit plus independent ID-hole discovery.

    Success means this batch was applied, never that the provider database is
    complete. There is no total, deletion contract or reliable tail watermark.
    """
    try:
        with sync_lock(data_dir):
            return _reconcile(data_dir,db_path,force)
    except BusyError:
        return dict(status='busy',reason='Загрузка ТрансТрейда уже выполняется.')


def _reconcile(data_dir,db_path,force):
    now=dt.datetime.now(MSK)
    with sqlite3.connect(db_path,timeout=30) as c:
        previous=reconciliation_status(c) or {}
        if previous.get('status')=='running':
            # We own the cross-process lock now, so the old owner was interrupted.
            previous=dict(previous,status='error',error='Предыдущая сверка истории прервана; прежние заявки сохранены.')
            save_reconciliation(c,previous)
        due=previous.get('next_attempt_at')
        if not force and due and now<dt.datetime.fromisoformat(due):
            return dict(previous,status='skipped',reason='Срок следующей сверки истории ещё не наступил.')
        floor,known=managed_scope(c,previous)
        attempt=dict(previous,status='running',attempted_at=now.isoformat(),scope_start=floor,
                     next_attempt_at=(now+RECONCILE_RETRY).isoformat(),complete=False)
        save_reconciliation(c,attempt)
    started=time.monotonic();http=None
    try:
        config=credentials(data_dir);http=transport(data_dir);config['_session']=http
        rows=get_orders(config,{})
        full_meta=dict(config.get('_response_meta',{}))
        ids=set();selected=[];fields=set()
        for raw in rows:
            r=normalize(raw);ident=r['id']
            if ident in ids:raise ValueError('Повтор ID в полном ответе ТрансТрейда; сверка не применена.')
            ids.add(ident);fields.update(raw)
            if r['date']>=floor or ident in known:selected.append(raw)
        if not ids and known:
            raise ValueError('ТрансТрейд вернул пустой полный список. История сохранена; сверка не применена.')
        missing=sorted((int(x) for x in known-ids),reverse=True)
        cursor=previous.get('known_cursor',max(missing,default=0)+1)
        rotated=[x for x in missing if x<cursor]+[x for x in missing if x>=cursor]
        known_targets=rotated[:max(1,MAX_ID_CHECKS//2)]
        ranges=gap_ranges(ids);gap_count=sum(b-a+1 for a,b in ranges)
        gap_cursor=previous.get('gap_cursor',max((int(x) for x in ids),default=0)+1)
        candidates=(x for x in rotate_gaps(ranges,gap_cursor) if str(x) not in known)
        gap_targets=list(islice(candidates,max(0,MAX_ID_CHECKS-len(known_targets))))
        recovered=[];found_ids=[];checked_gaps=[];checked_known=[]
        # Alternate queues: slow known omissions must not starve discovery.
        targets=(ident for pair in zip_longest(gap_targets,known_targets) for ident in pair if ident is not None)
        for ident in targets:
            if time.monotonic()-started>=MAX_RECONCILE_SECONDS:break
            found=get_orders(config,{'OrderId':ident})
            if len(found)>1 or any(normalize(r)['id']!=str(ident) for r in found):
                raise ValueError('ТрансТрейд вернул неверный ID в точечном поиске. Сверка не применена.')
            (checked_known if ident in known_targets else checked_gaps).append(ident)
            for raw in found:
                r=normalize(raw);found_ids.append(r['id'])
                if r['date']>=floor or r['id'] in known:recovered.append(raw)
        # Recheck local identity/scope inside the transaction; UI edits can occur
        # during downloads. apply() always preserves manual/deleted conflicts.
        with sqlite3.connect(db_path,timeout=30) as c:
            c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE')
            current_floor,current_known=managed_scope(c,previous)
            if current_floor!=floor or not current_known<=known:
                raise ValueError('Состав локальных заявок изменился во время сверки. Прежние данные сохранены; повторите загрузку.')
            end=max([now.date().isoformat()]+[str(r['BeginDateTime'])[:10] for r in selected+recovered])
            result=apply(c,selected,floor,end,recovered,full=True,checked_missing={str(x) for x in checked_known})
            unknown_gaps=gap_count-sum(any(a<=int(x)<=b for a,b in ranges) for x in known-ids)
            result.update(unfiltered_received=len(rows),unfiltered=full_meta,scope_start=floor,
                source_fields=sorted(fields),last_success_at=result['synced_at'],attempted_at=now.isoformat(),
                next_attempt_at=(dt.datetime.now(MSK)+RECONCILE_INTERVAL).isoformat(),
                discovered_by_id=sum(str(r['ID']) not in known for r in recovered),
                list_omitted_ids=[str(r['ID']) for r in recovered],id_found=len(found_ids),
                gap_count=gap_count,gap_checks=len(checked_gaps),known_id_checks=len(checked_known),
                gap_pending=max(0,unknown_gaps-len(checked_gaps)),
                known_pending=len(missing)-len(checked_known),
                gap_cursor=checked_gaps[-1] if checked_gaps else gap_cursor,
                known_cursor=checked_known[-1] if checked_known else cursor,
                seconds=round(time.monotonic()-started,3))
            save_reconciliation(c,result)
        return result
    except Exception as error:
        message=str(error) if isinstance(error,ValueError) else 'Не удалось сохранить сверку ТрансТрейда; предыдущие заявки сохранены.'
        failed=dict(attempt,status='error',error=message,
                    next_attempt_at=(dt.datetime.now(MSK)+RECONCILE_RETRY).isoformat())
        with sqlite3.connect(db_path,timeout=30) as c:save_reconciliation(c,failed)
        return failed
    finally:
        if http:http.close()
