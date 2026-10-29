"""Resumable daily history. One request at a time, at most three vehicles per day."""
import collections
import datetime as dt
import json
import math
import re
import threading
import uuid
import fcntl
import os

import requests

from app.importer import vehicle
from app.monitoring import Client, LOCK, snapshot, AuthenticationError, RateLimitError
from app.neftm import write_json

JOB_LOCK = threading.Lock()
MSK = dt.timezone(dt.timedelta(hours=3))
METRICS = {'mileage': 'vehicles/mileageAndMotohours', 'fuel': 'vehicles/fuelConsumption'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load(data_dir):
    path = data_dir / 'monitoring-history.json'
    return json.loads(path.read_text()) if path.exists() else {'cells': {}}


def key(vehicle_id, day):
    return f'{vehicle_id}:{day}'


def mappings(data_dir, names):
    """Exact, unique number match only; no fuzzy names or partner resource matching."""
    known = collections.defaultdict(list)
    for name in names:
        if re.fullmatch(r'[A-ZА-Я]\d{3}[A-ZА-Я]{2}\d{2,3}', name):
            known[vehicle(name)].append(name)
    candidates = []
    for row in (snapshot(data_dir) or {}).get('rows', []):
        plates = re.findall(r'(?<![A-ZА-Я0-9])[ABEKMHOPCTYXАВЕКМНОРСТУХ]\d{3}[ABEKMHOPCTYXАВЕКМНОРСТУХ]{2}\d{2,3}(?![A-ZА-Я0-9])', row['name'].upper())
        matches = known.get(vehicle(plates[0]), []) if len(plates) == 1 else []
        candidates.append({'vehicleId': row['vehicleId'], 'object': row['name'],
                           'vehicle': matches[0] if len(matches) == 1 else None})
    counts = collections.Counter(r['vehicle'] for r in candidates if r['vehicle'])
    for row in candidates:
        if counts[row['vehicle']] > 1:
            row['vehicle'] = None
        row['status'] = 'По уникальному госномеру' if row['vehicle'] else 'Не сопоставлен'
    return candidates


def period(start, end):
    try:
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except (ValueError, TypeError):
        raise ValueError('Укажите даты загрузки истории.') from None
    if a > b or (b-a).days > 92 or b >= dt.datetime.now(MSK).date():
        raise ValueError('Выберите до 93 завершённых дней; текущие сутки ещё не завершены.')
    return [(a+dt.timedelta(days=i)).isoformat() for i in range((b-a).days+1)]


def numeric(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def local_time(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return t.astimezone(MSK).replace(tzinfo=None) if t.tzinfo else t


def parse(result, ids, day, metric):
    """Do not accept duplicates, partial days or unexpected vehicles as complete history."""
    start = dt.datetime.fromisoformat(day)
    end = start+dt.timedelta(days=1)
    found = {}
    for row in result:
        ident = row.get('vehicleId')
        if type(ident) is not int or ident not in ids or ident in found:
            raise ValueError('История содержит неожиданный или повторяющийся объект.')
        periods = row.get('periods')
        if not isinstance(periods, list) or len(periods) > 1:
            raise ValueError('История содержит некорректные суточные периоды.')
        values = {'status': 'no_data', 'synced_at': now()}
        if periods:
            p = periods[0]
            try:
                if local_time(p['start']) != start or local_time(p['end']) != end:
                    raise ValueError()
            except (KeyError, TypeError, AttributeError, ValueError):
                raise ValueError('Границы истории не совпадают с запрошенными сутками МСК.') from None
            if metric == 'mileage':
                km, seconds = numeric(p.get('mileage')), numeric(p.get('motohours'))
                # All-zero counters cannot distinguish absence of telemetry from a real standstill.
                km_signal = any((numeric(p.get(k)) or 0) > 0 for k in ('mileage','mileageBegin','mileageEnd'))
                engine_signal = any((numeric(p.get(k)) or 0) > 0 for k in ('motohours','motohoursBegin','motohoursEnd'))
                values.update(km=km if km_signal else None,
                              engine_hours=seconds/3600 if seconds is not None and engine_signal else None)
                values['status'] = 'ok' if values['km'] is not None or values['engine_hours'] is not None else 'no_data'
            else:
                fuel = numeric(p.get('fuelConsumption'))
                signal = any((numeric(p.get(k)) or 0) > 0 for k in ('fuelConsumption','fuelLevelStart','fuelLevelEnd'))
                values.update(fuel_liters=fuel if signal else None,
                              status='ok' if signal and fuel is not None else 'no_signal')
        found[ident] = values
    return {ident: found.get(ident, {'status':'no_data', 'synced_at':now()}) for ident in ids}


def job_status(data_dir):
    path = data_dir / 'monitoring-history-job.json'
    job = json.loads(path.read_text()) if path.exists() else None
    if job and job['status'] == 'running':
        with open(data_dir/'monitoring-history.lock','a') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                job['status'] = 'interrupted'
                job['message'] = 'Загрузка прервана перезапуском. Продолжите: полученные порции сохранены.'
    return job


def start(data_dir, names, start_date, end_date, refresh=False):
    days = period(start_date, end_date)
    matched = [r for r in mappings(data_dir, names) if r['vehicle']]
    if not matched:
        raise ValueError('Нет однозначно сопоставленных объектов мониторинга.')
    if not JOB_LOCK.acquire(blocking=False):
        raise ValueError('История уже загружается.')
    lock = open(data_dir/'monitoring-history.lock','a')
    os.chmod(data_dir/'monitoring-history.lock',0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close();JOB_LOCK.release()
        raise ValueError('История уже загружается.') from None
    job = {'id':uuid.uuid4().hex, 'from':start_date, 'to':end_date, 'status':'running',
           'total':len(matched)*len(days)*2, 'done':0, 'failed':0, 'started_at':now(),
           'message':'Получаем историю небольшими порциями.', 'refresh':refresh}
    try:
        write_json(data_dir/'monitoring-history-job.json',job)
        threading.Thread(target=run, args=(data_dir,matched,days,job,lock), daemon=True).start()
    except Exception:
        JOB_LOCK.release()
        lock.close()
        raise
    return dict(job)


def run(data_dir, matched, days, job, lock=None):
    def progress():
        job['updated_at'] = now()
        write_json(data_dir/'monitoring-history-job.json',job)
    try:
        history = load(data_dir)
        with requests.Session() as session:
            client = Client(data_dir, session)
            for day in days:
                for metric, method in METRICS.items():
                    pending = []
                    for obj in matched:
                        cell = history['cells'].get(key(obj['vehicleId'], day), {})
                        if not job['refresh'] and metric in cell:
                            job['done'] += 1
                        else:
                            pending.append(obj)
                    for offset in range(0,len(pending),3):
                        batch = pending[offset:offset+3]
                        ids = [o['vehicleId'] for o in batch]
                        job['current'] = f'{day} · '+('пробег / моточасы' if metric=='mileage' else 'расход топлива')
                        progress()
                        body = {'vehicleIds':ids, 'sampling':86400, 'from':day+'T00:00:00',
                                'to':(dt.date.fromisoformat(day)+dt.timedelta(days=1)).isoformat()+'T00:00:00', 'timezone':3}
                        try:
                            # The same lock also guards token refresh/current-object synchronization.
                            with LOCK:
                                result = parse(client.read(method,body),ids,day,metric)
                        except (AuthenticationError, RateLimitError):
                            raise
                        except ValueError:
                            # Split a failed batch; retry each vehicle once. Never loop on login failure.
                            result = {}
                            if len(batch)>1:
                                for ident in ids:
                                    try:
                                        with LOCK:
                                            result.update(parse(client.read(method,{**body,'vehicleIds':[ident]}),[ident],day,metric))
                                    except (AuthenticationError, RateLimitError):
                                        raise
                                    except ValueError:
                                        pass
                        for obj in batch:
                            ident = obj['vehicleId']
                            if ident not in result:
                                job['failed'] += 1
                                continue
                            cell = history['cells'].setdefault(key(ident,day),{'vehicleId':ident,'date':day})
                            old = cell.get(metric)
                            # A transient empty response must not erase known valid readings.
                            if not old or old.get('status') != 'ok' or result[ident]['status']=='ok':
                                incoming = dict(result[ident])
                                if old and metric == 'mileage':
                                    for field in ('km','engine_hours'):
                                        if incoming.get(field) is None and old.get(field) is not None:
                                            incoming[field] = old[field]
                                            incoming['retained_at'] = old['synced_at']
                                cell[metric] = incoming
                            job['done'] += 1
                        write_json(data_dir/'monitoring-history.json',history)
                        progress()
                        if job['failed'] >= 9:
                            raise ValueError('Много ошибок провайдера. Загрузка остановлена; продолжение пропустит сохранённые порции.')
            job['status'] = 'partial' if job['failed'] else 'complete'
            job['message'] = 'Часть запросов не завершена. Нажмите «Продолжить загрузку».' if job['failed'] else 'Все порции получены. Отсутствующие показания отмечены отдельно.'
    except (AuthenticationError, RateLimitError) as error:
        job['status'] = 'partial'
        job['message'] = str(error) + ' Полученные порции сохранены.'
    except Exception:
        job['status'] = 'partial'
        job['message'] = 'Загрузка прервана. Полученные порции сохранены; можно продолжить.'
    finally:
        job['finished_at'] = now()
        try:
            progress()
        finally:
            JOB_LOCK.release()
            if lock:lock.close()


def daily_rows(data_dir, names):
    mapping = {r['vehicleId']:r for r in mappings(data_dir,names) if r['vehicle']}
    rows = []
    for cell in load(data_dir)['cells'].values():
        obj = mapping.get(cell['vehicleId'])
        if not obj:
            continue
        mileage, fuel = cell.get('mileage',{}), cell.get('fuel',{})
        fuel_value, fuel_status = fuel.get('fuel_liters'), fuel.get('status','pending')
        # Provider zero with substantial driving is not a credible consumption measurement.
        # Retain the original response in the cache, but exclude it from derived fuel ratios.
        if fuel_value == 0 and (mileage.get('km') or 0) > 1:
            fuel_value, fuel_status = None, 'suspect_zero'
        rows.append({'date':cell['date'],'vehicle':obj['vehicle'],'object':obj['object'],
                     'km':mileage.get('km'),'engine_hours':mileage.get('engine_hours'),
                     'fuel_liters':fuel_value, 'hours':None,
                     'mileage_status':mileage.get('status','pending'), 'fuel_status':fuel_status,
                     'source':'ГЛОНАССсофт API', 'synced_at':max(mileage.get('synced_at',''),fuel.get('synced_at',''))})
    return sorted(rows,key=lambda r:(r['date'],r['vehicle']))


def merge_satellite(excel, api):
    """API supersedes same metric/day, never adds a duplicate to the Excel baseline."""
    grouped = collections.defaultdict(list)
    for row in excel:
        grouped[(row['vehicle'],row['date'])].append(row)
    merged = {}
    fields = ('km','hours','engine_hours','movement_hours','stop_hours','fuel_liters')
    for k, rows in grouped.items():
        entry = {'vehicle':k[0], 'date':k[1], 'source':'Excel', 'sources':{}}
        for f in fields:
            entry[f] = sum(r[f] for r in rows) if all(r.get(f) is not None for r in rows) else None
            if entry[f] is not None:entry['sources'][f]='Excel'
        merged[k]=entry
    for row in api:
        k=(row['vehicle'],row['date'])
        entry=merged.setdefault(k,{'vehicle':k[0],'date':k[1],**{f:None for f in fields},'sources':{}})
        for f in ('km','engine_hours','fuel_liters'):
            if row.get(f) is not None:
                entry[f]=row[f];entry['sources'][f]='ГЛОНАССсофт API'
        entry.update(mileage_status=row['mileage_status'],fuel_status=row['fuel_status'],synced_at=row['synced_at'])
        if entry.get('fuel_liters') == 0 and (entry.get('km') or 0) > 1:
            entry['fuel_liters'] = None
            entry['fuel_status'] = 'suspect_zero'
            entry['sources'].pop('fuel_liters',None)
        entry['source']=' + '.join(sorted(set(entry['sources'].values()))) or 'Нет показаний'
    return list(merged.values())
