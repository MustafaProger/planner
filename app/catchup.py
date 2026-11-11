"""Durable coverage of successful API reads, never proof of business completeness.

Only closed Moscow calendar days are covered. A successful empty response is a
read too; failed or interrupted calls must never invoke ``mark_success``.
"""
import datetime as dt
import fcntl
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

MSK = dt.timezone(dt.timedelta(hours=3))
SOURCES = ('transtrade', 'neftm', 'rosneft', 'monitoring')
STATE_FILE = 'refresh-coverage.json'
MAX_MARK_DAYS = 93


def _day(value):
    if isinstance(value, dt.datetime):
        raise ValueError('Укажите календарную дату, а не время.')
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        raise ValueError('Укажите дату в формате ГГГГ-ММ-ДД.')
    try:
        result = dt.date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError()
        return result
    except ValueError:
        raise ValueError('Укажите дату в формате ГГГГ-ММ-ДД.') from None


def _stamp(value=None):
    if value is None:
        return dt.datetime.now(MSK)
    try:
        result = dt.datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(result, dt.datetime) or result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(MSK)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Время успешной загрузки должно содержать часовой пояс.') from None


def _source(source):
    if source not in SOURCES:
        raise ValueError('Неизвестный источник для догрузки.')


def _dates(first, last):
    for offset in range(max(0, (last-first).days+1)):
        yield first+dt.timedelta(days=offset)


def _json(path):
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, OSError):
        raise ValueError(f'Не удалось прочитать состояние {path.name}; прежние данные не изменены.') from None


@contextmanager
def _locked(folder):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder/'refresh-coverage.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read(folder):
    path = folder/STATE_FILE
    if not path.exists():
        return {'version': 1, 'sources': {}}
    value = _json(path)
    try:
        if value.get('version') != 1 or not isinstance(value.get('sources'), dict):
            raise ValueError()
        if value.get('scope_start'):
            _day(value['scope_start'])
        for source, entry in value['sources'].items():
            _source(source)
            if not isinstance(entry, dict) or not isinstance(entry.get('days', {}), dict):
                raise ValueError()
            for day, stamp in entry.get('days', {}).items():
                if stamp is None or _day(day) >= _stamp(stamp).date():
                    raise ValueError()
            for day, stamp in entry.get('open_days', {}).items():
                if stamp is None or _day(day) != _stamp(stamp).date():
                    raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Повреждено состояние догрузки; сохранённый файл не заменён.') from None


def _write(folder, value):
    path = folder/STATE_FILE
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.name, dir=folder)
    try:
        with os.fdopen(descriptor, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(value, out, ensure_ascii=False, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        directory = os.open(folder, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _database(db_path):
    """Read owning data without creating/migrating a database or inspecting secrets."""
    path = Path(db_path)
    if not path.exists():
        return [], {}
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=5) as connection:
            tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
            dates, meta = [], {}
            if 'records' in tables:
                columns = {row[1] for row in connection.execute('pragma table_info(records)')}
                if {'kind', 'body'} <= columns:
                    suffix = ' and deleted=0' if 'deleted' in columns else ''
                    for row in connection.execute("select body from records where kind in ('trips','satellite')"+suffix):
                        body = json.loads(row[0])
                        try:
                            dates.append(_day(body.get('date')))
                        except ValueError:
                            continue
            if 'workspace_meta' in tables:
                for key, body in connection.execute("select key,body from workspace_meta where key in ('transtrade_runs','transtrade_reconciliation')"):
                    meta[key] = json.loads(body)
            return dates, meta
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        raise ValueError('Не удалось прочитать периоды рабочей базы; очередь догрузки не изменена.') from None


def _fuel(folder, source):
    from app.fuel_history import read
    try:
        value = read(folder, source)
        periods = value.get('periods') or []
        if not periods and value.get('from') and value.get('to'):
            periods = [{'from': value['from'], 'to': value['to'], 'synced_at': value.get('synced_at')}]
        if not isinstance(periods, list):
            raise ValueError()
        return periods
    except (ValueError, OSError, TypeError, AttributeError):
        raise ValueError(f'Не удалось прочитать историю {source}; очередь догрузки не изменена.') from None


def _period(period, start='from', end='to', stamp='synced_at'):
    try:
        if period[stamp] is None:
            return None
        first, last, at = _day(period[start]), _day(period[end]), _stamp(period[stamp])
        if first > last:
            return None
        return first, last, at
    except (ValueError, KeyError, TypeError):
        return None


def _add_range(days, first, last, at, floor):
    # A query made before midnight cannot certify that day's final response.
    for day in _dates(max(first, floor), min(last, at.date()-dt.timedelta(days=1))):
        key, stamp = day.isoformat(), at.isoformat()
        if key not in days or _stamp(days[key]) < at:
            days[key] = stamp


def _observations(folder, db_path, requested_source):
    dates, meta = _database(db_path)
    intervals = {source: [] for source in SOURCES}
    explicit_starts = []
    for item in meta.get('transtrade_runs') or []:
        if not isinstance(item, dict) or item.get('status') != 'success':
            continue
        value = _period(item, 'start', 'end')
        try:
            explicit_starts.append(_day(item['start']))
        except (ValueError, KeyError, TypeError):
            pass
        if value:
            intervals['transtrade'].append(value)
    full = meta.get('transtrade_reconciliation') or {}
    if isinstance(full, dict) and full.get('last_success_at'):
        value = _period(full, 'start', 'end', 'last_success_at')
        if value:
            intervals['transtrade'].append(value)
            dates.append(value[0])
    for source in ('neftm', 'rosneft'):
        try:
            periods = _fuel(folder, source)
        except ValueError:
            if requested_source == source:
                raise
            periods = []  # One provider's damaged cache must not stop the others.
        for item in periods:
            try:
                explicit_starts.append(_day(item['from']))
            except (ValueError, KeyError, TypeError):
                pass
            value = _period(item)
            if value:
                intervals[source].append(value)
    path = folder/'monitoring-history.json'
    try:
        cells = (_json(path).get('cells') or {}) if path.exists() else {}
        if not isinstance(cells, dict):
            raise ValueError('Не удалось прочитать периоды истории спутника.')
    except ValueError:
        if requested_source == 'monitoring':
            raise
        cells = {}
    for cell in cells.values():
        try:
            dates.append(_day(cell['date']))
        except (ValueError, KeyError, TypeError):
            continue
    return dates+explicit_starts, explicit_starts, intervals, cells


def _monitoring(folder, names, cells, floor):
    from app.monitoring_history import mappings
    try:
        ids = sorted({row['vehicleId'] for row in mappings(folder, names) if row.get('vehicle')})
    except (ValueError, OSError, TypeError, KeyError, AttributeError):
        raise ValueError('Не удалось проверить сопоставления объектов спутника.') from None
    if not ids:
        return [], {}
    per_day = {}
    for cell in cells.values():
        try:
            day = _day(cell['date'])
            ident = cell['vehicleId']
            if day < floor or type(ident) is not int or ident not in ids:
                continue
            stamps = []
            for metric in ('mileage', 'fuel'):
                value = cell[metric]
                if value.get('status') not in ('ok', 'no_data', 'no_signal') or value.get('synced_at') is None:
                    raise ValueError()
                at = _stamp(value['synced_at'])
                if day >= at.date():
                    raise ValueError()
                stamps.append(at)
            per_day.setdefault(day, {})[ident] = min(stamps)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    covered = {day.isoformat(): min(by_id.values()).isoformat()
               for day, by_id in per_day.items() if set(by_id) == set(ids)}
    return ids, covered


def plan(data_dir, db_path, source, *, today=None, names=(), limit_days=7, monitoring_attempts=None):
    """Return the next missing closed interval, within one month.

    The monitoring worker prioritizes recent gaps and rotates incomplete days
    without marking them covered. Other callers use oldest-first selection.

    Every caller may merge independently saved source responses. This makes
    bootstrap and manual successful imports usable after worker restart too.
    """
    _source(source)
    if type(limit_days) is not int or not 1 <= limit_days <= 31:
        raise ValueError('Порция догрузки должна содержать от 1 до 31 дня.')
    monitoring_queue = source == 'monitoring' and monitoring_attempts is not None
    clock = _stamp(today) if monitoring_queue else None
    day = clock.date() if clock else _day(today) if today is not None else dt.datetime.now(MSK).date()
    yesterday = day-dt.timedelta(days=1)
    folder = Path(data_dir)
    with _locked(folder):
        state = _read(folder)
        before = json.dumps(state, sort_keys=True)
        dates, explicit_starts, intervals, cells = _observations(folder, db_path, source)
        configured = os.environ.get('FLEET_SYNC_FROM')
        if configured:
            floor = _day(configured)
            if floor > day:
                raise ValueError('Начало догрузки не может находиться в будущем.')
        elif state.get('scope_start') and state.get('scope_inferred', True):
            floor = min([_day(state['scope_start'])]+explicit_starts)
        else:
            candidates = [value for value in dates if value <= day]+([_day(state['scope_start'])] if state.get('scope_start') else [])
            floor = min(candidates, default=day.replace(day=1))
        state['scope_start'] = floor.isoformat()
        state['scope_inferred'] = True
        entry = state['sources'].setdefault(source, {'days': {}})
        days = entry.setdefault('days', {})
        for first, last, at in intervals[source]:
            _add_range(days, first, last, at, floor)
        if source == 'monitoring':
            ids, observed = _monitoring(folder, names, cells, floor)
            if entry.get('vehicle_ids') != ids:
                # A newly mapped vehicle needs its own history even on dates
                # previously read for the old vehicle set.
                days = entry['days'] = {}
            entry['vehicle_ids'] = ids
            for key, stamp in observed.items():
                if key not in days or _stamp(days[key]) < _stamp(stamp):
                    days[key] = stamp
            if not ids:
                days.clear()
        # Provider caches usually timestamp completion, not request start. A
        # response crossing midnight must not undo our explicit open-day mark.
        for key in entry.get('open_days', {}):
            days.pop(key, None)
        first = last = None
        pending = 0
        deferred = {}
        choices = []
        recent_start = day-dt.timedelta(days=30)
        maximum = 1 if source == 'monitoring' else limit_days
        for missing in _dates(floor, yesterday):
            key = missing.isoformat()
            if key in days:
                continue
            pending += 1
            if monitoring_queue:
                attempt = monitoring_attempts.get(key)
                if attempt:
                    deferred[key] = attempt
                    if clock-_stamp(attempt) < dt.timedelta(hours=1):
                        continue
                # Fresh gaps first; within each tier, give every date a turn
                # before retrying the same incomplete dates.
                choices.append((missing < recent_start, attempt or '', missing))
                continue
            if first is None:
                first = last = missing
            elif missing == last+dt.timedelta(days=1) and missing.month == first.month and (missing-first).days < maximum:
                last = missing
        if choices:
            first = last = min(choices)[2]
        if before != json.dumps(state, sort_keys=True):
            state['updated_at'] = _stamp().isoformat()
            _write(folder, state)
        return {'scope_start': floor.isoformat(), 'target_end': yesterday.isoformat(),
                'from': first.isoformat() if first else None,
                'to': last.isoformat() if last else None, 'pending_days': pending,
                **(dict(monitoring_attempts=deferred, target_covered=yesterday.isoformat() in days)
                   if monitoring_queue else {})}


def _read_range(source, start, end, at):
    _source(source)
    first, last, stamp = _day(start), _day(end), _stamp(at)
    if first > last or (last-first).days >= MAX_MARK_DAYS:
        raise ValueError('Отметьте успешную порцию длиной от 1 до 93 дней.')
    if last > stamp.date():
        raise ValueError('Нельзя подтвердить загрузку будущих суток.')
    return first, last, stamp


def _open_read(entry, first, last, stamp):
    if first <= stamp.date() <= last:
        key = stamp.date().isoformat()
        entry.setdefault('open_days', {})[key] = stamp.isoformat()
        entry.setdefault('days', {}).pop(key, None)
        return 1
    return 0


def begin_read(data_dir, source, start, end, *, at=None):
    """Persist an open-day barrier before a request can commit source data.

    This cannot advance coverage or establish a history scope. If the process
    dies after the API cache commit but before its checkpoint, bootstrap still
    knows the response began before this day's final midnight boundary.
    """
    first, last, stamp = _read_range(source, start, end, at)
    if not first <= stamp.date() <= last:
        return 0
    folder = Path(data_dir)
    with _locked(folder):
        state = _read(folder)
        entry = state['sources'].setdefault(source, {'days': {}})
        count = _open_read(entry, first, last, stamp)
        state['updated_at'] = _stamp().isoformat()
        _write(folder, state)
        return count


def mark_success(data_dir, source, start, end, *, at=None):
    """Record a committed successful API response; return closed days covered.

    ``at`` is the request start time, with a timezone, matching ``begin_read``.
    Calls may include the current day, but that open day remains pending after
    midnight even when the response finished after midnight.
    """
    first, last, stamp = _read_range(source, start, end, at)
    folder = Path(data_dir)
    with _locked(folder):
        state = _read(folder)
        before = json.dumps(state, sort_keys=True)
        entry = state['sources'].setdefault(source, {'days': {}})
        days = entry.setdefault('days', {})
        if not state.get('scope_start'):
            state['scope_inferred'] = False
        floor = min(_day(state['scope_start']), first) if state.get('scope_start') else first
        state['scope_start'] = floor.isoformat()
        _add_range(days, first, last, stamp, floor)
        open_days = entry.setdefault('open_days', {})
        for day in _dates(first, min(last, stamp.date()-dt.timedelta(days=1))):
            open_days.pop(day.isoformat(), None)
        _open_read(entry, first, last, stamp)
        entry['last_marked_at'] = stamp.isoformat()
        if before != json.dumps(state, sort_keys=True):
            state['updated_at'] = _stamp().isoformat()
            _write(folder, state)
    return max(0, (min(last, stamp.date()-dt.timedelta(days=1))-first).days+1)
