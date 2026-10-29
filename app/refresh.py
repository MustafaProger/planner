"""Periodic, read-only provider synchronization; never re-import Excel automatically."""
import copy
import datetime as dt
import fcntl
import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path

from app.neftm import write_json

INTERVAL = 300
MSK = dt.timezone(dt.timedelta(hours=3))
SOURCE_NAMES = {'transtrade': 'ТрансТрейд', 'neftm': 'Нефтьмагистраль',
                'rosneft': 'Роснефть', 'monitoring': 'ГЛОНАССсофт'}


def now():
    return dt.datetime.now(MSK)


def period(start=None, end=None, today=None):
    today = today or now().date()
    if start is None and end is None:
        return today.replace(day=1).isoformat(), today.isoformat()
    try:
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        if not 0 <= (b-a).days < 31:
            raise ValueError()
        return a.isoformat(), b.isoformat()
    except (TypeError, ValueError):
        raise ValueError('Для общего обновления выберите период от 1 до 31 дня.') from None


class RefreshService:
    def __init__(self, data_dir, db_path, get_dataset):
        self.data_dir, self.db_path = Path(data_dir), Path(db_path)
        self.get_dataset = get_dataset
        self.guard = threading.RLock()
        self.running = False
        self.stop_event = threading.Event()
        self.scheduler = None
        self.state_path = self.data_dir / 'refresh-state.json'

    def _read(self):
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except (OSError, ValueError):
                pass
        return {'status': 'idle', 'sources': {}, 'interval_seconds': INTERVAL}

    def _save(self, state):
        state['updated_at'] = now().isoformat()
        write_json(self.state_path, state)

    def status(self):
        with self.guard:
            state = self._read()
            if state.get('status') == 'running' and not self.running:
                # A persistent lock distinguishes another process from an interrupted job.
                lock = self._lock('refresh-run.lock')
                if lock:
                    lock.close()
                    state['status'] = 'interrupted'
                    state['message'] = 'Обновление прервано перезапуском. Полученные данные сохранены.'
            state['interval_seconds'] = INTERVAL
            state['automatic_scope'] = 'Текущий месяц по МСК; история спутника — последние завершённые сутки.'
            state['server_scheduler'] = bool(self.scheduler and self.scheduler.is_alive())
            return state

    def _lock(self, name):
        handle = (self.data_dir/name).open('a')
        os.chmod(handle.name, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        return handle

    def start(self, start=None, end=None, *, trigger='manual', user_id=None):
        start, end = period(start, end)
        with self.guard:
            if self.running:
                return dict(self.status(), accepted=False)
            lock = self._lock('refresh-run.lock')
            if not lock:
                return dict(self.status(), accepted=False)
            old = self._read()
            state = {'id': uuid.uuid4().hex, 'status': 'running', 'trigger': trigger,
                     'from': start, 'to': end, 'started_at': now().isoformat(),
                     'last_success_at': old.get('last_success_at'),
                     'last_finished_at': old.get('last_finished_at'),
                     'interval_seconds': INTERVAL,
                     'next_run_at': (now()+dt.timedelta(seconds=INTERVAL)).isoformat(),
                     'sources': {key: {'name': label, 'status': 'pending',
                        'last_success_at': old.get('sources', {}).get(key, {}).get('last_success_at')}
                        for key, label in SOURCE_NAMES.items()}}
            self.running = True
            try:
                self._save(state)
                threading.Thread(target=self._run, args=(state, lock, user_id), daemon=True,
                                 name='fleet-refresh-job').start()
            except Exception:
                self.running = False
                lock.close()
                raise
            return dict(copy.deepcopy(state), accepted=True)

    def _source(self, state, key, **values):
        with self.guard:
            state['sources'][key].update(values)
            self._save(state)

    def _run(self, state, lock, user_id):
        from app import transtrade, neftm, rosneft, monitoring, monitoring_history
        checks = {'transtrade': lambda: transtrade.configured(self.data_dir),
                  'neftm': lambda: (self.data_dir/'neftm-api.key').is_file(),
                  'rosneft': lambda: rosneft.configured(self.data_dir),
                  'monitoring': lambda: monitoring.configured(self.data_dir)}
        try:
            for key in SOURCE_NAMES:
                try:
                    if not checks[key]():
                        self._source(state, key, status='unconfigured', message='Подключение не настроено.')
                        continue
                    self._source(state, key, status='running', message='Получаем данные из источника…')
                    if key == 'transtrade':
                        result = transtrade.sync(self.data_dir, self.db_path, state['from'], state['to'])
                        message = f"Получено {result['received']} заявок."
                    elif key in ('neftm', 'rosneft'):
                        provider = neftm if key == 'neftm' else rosneft
                        result = provider.sync(self.data_dir, state['from'], state['to'])
                        message = f"Получено {len(result['rows'])} операций."
                    else:
                        current = monitoring_history.job_status(self.data_dir)
                        if current and current['status'] == 'running':
                            self._source(state, key, status='busy', message='История уже загружается; повторный запрос пропущен.')
                            continue
                        result = monitoring.sync(self.data_dir)
                        yesterday = now().date()-dt.timedelta(days=1)
                        end = min(dt.date.fromisoformat(state['to']), yesterday)
                        start = (end if state['trigger'] == 'automatic' else dt.date.fromisoformat(state['from']))
                        message = f"Обновлено {len(result['rows'])} объектов."
                        if start <= end:
                            job = monitoring_history.start(self.data_dir, self.get_dataset()['vehicles'],
                                                           start.isoformat(), end.isoformat(), refresh=True)
                            while True:
                                self.stop_event.wait(1)
                                current = monitoring_history.job_status(self.data_dir)
                                if not current or current.get('id') != job['id']:
                                    raise ValueError('Не удалось подтвердить завершение истории спутника.')
                                if current['status'] != 'running':
                                    break
                                if self.stop_event.is_set():
                                    raise ValueError('Сервер останавливается; полученные порции сохранены.')
                            if current['status'] != 'complete':
                                raise ValueError(current.get('message', 'История спутника загружена не полностью.'))
                            message += f" История: {start.isoformat()} — {end.isoformat()}."
                        else:
                            message += ' Завершённых суток в выбранном периоде нет.'
                    self._source(state, key, status='success', message=message, last_success_at=now().isoformat())
                except ValueError as error:
                    self._source(state, key, status='error', message=str(error))
                except Exception:
                    self._source(state, key, status='error', message='Источник не удалось обновить. Предыдущие данные сохранены; повторите позже.')
            statuses = [s['status'] for s in state['sources'].values()]
            state['status'] = ('partial' if any(s in ('error', 'busy') for s in statuses)
                               else 'success' if 'success' in statuses else 'idle')
            state['last_finished_at'] = now().isoformat()
            if state['status'] == 'success':
                state['last_success_at'] = state['last_finished_at']
            # Long requests must never queue a burst of catch-up jobs.
            scheduled = dt.datetime.fromisoformat(state['next_run_at'])
            if scheduled <= now():
                state['next_run_at'] = (now()+dt.timedelta(seconds=INTERVAL)).isoformat()
            with sqlite3.connect(self.db_path, timeout=30) as c:
                c.execute('insert into audit(at,user_id,action,detail) values(?,?,?,?)',
                          (now().isoformat(), user_id, 'refresh '+state['trigger'],
                           json.dumps({'from': state['from'], 'to': state['to'], 'status': state['status'],
                                       'sources': {k: v['status'] for k, v in state['sources'].items()}}, ensure_ascii=False)))
        except Exception:
            state['status'] = 'partial'
            state['last_finished_at'] = now().isoformat()
            state['message'] = 'Обновление завершено с ошибкой. Проверьте состояние источников.'
        finally:
            with self.guard:
                try:
                    self._save(state)
                finally:
                    self.running = False
                    lock.close()

    def start_scheduler(self):
        if self.scheduler and self.scheduler.is_alive():
            return
        self.stop_event.clear()
        self.scheduler = threading.Thread(target=self._schedule, daemon=True, name='fleet-refresh-schedule')
        self.scheduler.start()

    def _schedule(self):
        leader = self._lock('refresh-scheduler.lock')
        if not leader:
            return
        try:
            with self.guard:
                state = self._read()
                state['next_run_at'] = (now()+dt.timedelta(seconds=INTERVAL)).isoformat()
                self._save(state)
            while not self.stop_event.wait(1):
                state = self.status()
                due = dt.datetime.fromisoformat(state['next_run_at'])
                if not self.running and now() >= due:
                    self.start(trigger='automatic')
        finally:
            leader.close()

    def stop(self):
        self.stop_event.set()


def register(app, auth, data_dir, db_path, get_dataset):
    from flask import jsonify, request, session
    service = RefreshService(data_dir, db_path, get_dataset)

    @app.get('/api/refresh')
    @auth()
    def refresh_status():
        return jsonify(service.status())

    @app.post('/api/refresh')
    @auth(['admin'])
    def refresh_start():
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError('Укажите параметры обновления.')
        return jsonify(service.start(body.get('from'), body.get('to'), user_id=session.get('uid'))), 202

    return service
