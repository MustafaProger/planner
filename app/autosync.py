"""Independent durable source schedules; the worker supervises this scheduler.

The queue records successful reads, not business completeness. Each provider has
one current/history job at a time, so a slow source cannot stop other sources.
"""
import copy
import datetime as dt
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from app.neftm import write_json

MSK = dt.timezone(dt.timedelta(hours=3))
NAMES = {'transtrade': 'ТрансТрейд', 'neftm': 'Нефтьмагистраль',
         'rosneft': 'Роснефть', 'monitoring': 'ГЛОНАССсофт'}
STATE = 'refresh-auto.json'
HEARTBEAT = 'refresh-heartbeat.json'
CURRENT_DEADLINE = 900
HISTORY_DEADLINE = 1800
logger = logging.getLogger(__name__)


def now():
    return dt.datetime.now(MSK)


def stamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def read_state(folder):
    path = Path(folder)/STATE
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('tasks'), dict):
        raise ValueError('Повреждено расписание обновления.')
    for key, task in value['tasks'].items():
        if key not in {source+':'+kind for source in NAMES for kind in ('current','history')} or not isinstance(task, dict):
            raise ValueError('Повреждено расписание обновления.')
        if 'next_run_at' in task and stamp(task['next_run_at']) is None:
            raise ValueError('Повреждён срок следующего обновления.')
    return value


def public_status(folder, expected=True):
    from app.health import read_worker_health
    state = read_state(folder)
    if state is None:
        return None
    health = read_worker_health(folder)
    sources = {}
    for key, name in NAMES.items():
        current = state['tasks'].get(key+':current', {})
        history = state['tasks'].get(key+':history', {})
        value = dict(current, name=name)
        value.setdefault('status', 'pending')
        value['catchup'] = {k: history.get(k) for k in ('status','pending_days','from','to','last_success_at','message')}
        if (current.get('status') != 'unconfigured' and history.get('status') != 'unconfigured'
                and (history.get('status') == 'error' or history.get('error_since'))):
            value['status'] = 'error'
            value['error_since'] = history.get('error_since') or current.get('error_since')
            value['message'] = current.get('message','')+' Догрузка: '+history.get('message','не завершена.')
        sources[key] = value
    running = any(x.get('status') == 'running' for x in state['tasks'].values())
    failures = any(x.get('status') in ('error', 'busy', 'interrupted') for x in sources.values())
    successful = [x.get('last_success_at') for x in sources.values() if x.get('last_success_at')]
    due = [x['next_run_at'] for x in state['tasks'].values() if x.get('next_run_at')]
    return dict(id=state.get('id'), status='running' if running else 'partial' if failures else 'success' if successful else 'idle',
        trigger='automatic', sources=sources, started_at=state.get('started_at'),
        last_finished_at=state.get('last_finished_at'), last_success_at=state.get('last_success_at'),
        next_run_at=min(due) if due else None, server_scheduler=health['healthy'],
        heartbeat_at=health.get('heartbeat_at'), scheduler_expected=expected,
        message=state.get('message',''), **{'from':now().date().replace(day=1).isoformat(),'to':now().date().isoformat()})


class IncompleteMonitoringDay(ValueError):
    pass


class Scheduler:
    def __init__(self, service, interval):
        self.service, self.interval = service, interval
        self.folder = service.data_dir
        self.guard = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.threads = {}
        self.jobs = {}
        self.state = None
        self.heartbeat_at = None
        self.storage_error = None
        self.leader = False
        self.alert_thread = None
        self.alert_due = 0

    def _load(self):
        try:
            value = read_state(self.folder)
        except (ValueError, OSError):
            # Only execution metadata is rebuildable. Preserve its damaged copy;
            # never reset the coverage ledger or business/source data this way.
            path = self.folder/STATE
            if path.exists():
                path.rename(self.folder/(STATE+'.corrupt-'+uuid.uuid4().hex))
            value = None
        value = value or dict(version=1, id=uuid.uuid4().hex, started_at=now().isoformat(), tasks={})
        try:
            old = json.loads((self.folder/'refresh-state.json').read_text())
            legacy = old.get('sources', {}) if isinstance(old,dict) else {}
            if not isinstance(legacy,dict):legacy = {}
        except (OSError,ValueError):
            legacy = {}
        for key in NAMES:
            for kind in ('current','history'):
                task = value['tasks'].setdefault(key+':'+kind, {})
                # Preserve known freshness when upgrading from the old schedule;
                # an application restart must not hide an already stale source.
                prior = legacy.get(key, {})
                prior = prior.get('last_success_at') if isinstance(prior,dict) else None
                if kind == 'current' and not task.get('last_success_at') and stamp(prior):
                    task['last_success_at'] = prior
                task.setdefault('status','pending')
                task.setdefault('next_run_at', now().isoformat())
                if task['status'] == 'running':
                    task.update(status='interrupted', next_run_at=now().isoformat(),
                                message='Прерванная загрузка будет продолжена автоматически.')
        self.state = value

    def _save(self):
        self.state['updated_at'] = now().isoformat()
        write_json(self.folder/STATE, self.state)

    def _configured(self, source):
        from app import transtrade, neftm, rosneft, monitoring
        if source == 'neftm':
            return (self.folder/'neftm-api.key').is_file()
        return {'transtrade':transtrade,'rosneft':rosneft,'monitoring':monitoring}[source].configured(self.folder)

    def _launch(self, source, kind):
        key = source+':'+kind
        with self.guard:
            if any(x.startswith(source+':') for x in self.jobs):
                return
            task = self.state['tasks'][key]
            at = now()
            if stamp(task.get('next_run_at')) > at:
                return
            try:
                configured = self._configured(source)
                required = os.environ.get('FLEET_REQUIRED_PROVIDERS','').split(',')
                if not configured and source in required:
                    raise ValueError('Required provider is unconfigured')
            except Exception:
                task.update(status='error', message='Не удалось проверить настройки подключения источника.',
                            last_attempt_at=at.isoformat(), error_since=task.get('error_since') or at.isoformat(),
                            next_run_at=(at+dt.timedelta(seconds=self.interval)).isoformat())
                self._save()
                return
            if not configured:
                task.update(status='unconfigured', message='Подключение не настроено.',
                            next_run_at=(at+dt.timedelta(seconds=self.interval)).isoformat())
                self._save()
                return
            task.update(status='running', started_at=at.isoformat(), last_attempt_at=at.isoformat(),
                        next_run_at=(at+dt.timedelta(seconds=self.interval)).isoformat())
            self._save()  # Persist before any provider read; crash replays safely.
            self.jobs[key] = dict(started_at=at.isoformat(), deadline_at=(at+dt.timedelta(
                seconds=CURRENT_DEADLINE if kind=='current' else HISTORY_DEADLINE)).isoformat())
            thread = threading.Thread(target=self._job, args=(source,kind), daemon=True, name='fleet-'+key)
            self.threads[key] = thread
            try:thread.start()
            except Exception:
                self.jobs.pop(key,None)
                task.update(status='error',message='Не удалось запустить обновление; будет повторная попытка.')
                self._save()
                raise

    def _job(self, source, kind):
        key = source+':'+kind
        try:
            values = self._current(source) if kind == 'current' else self._history(source)
            outcome = dict(status='success', last_success_at=now().isoformat(), error_since=None, **values)
        except Exception as error:
            # Provider modules expose redacted ValueErrors; unexpected exceptions
            # may contain request secrets and must never enter status/log output.
            message = str(error) if isinstance(error,ValueError) else 'Обновление не завершено. Сохранённые данные остаются доступными.'
            outcome = dict(status='error', message=message)
        with self.guard:
            task = self.state['tasks'][key]
            if outcome['status']=='error':
                outcome['error_since'] = task.get('error_since') or task['started_at']
            task.update(outcome, finished_at=now().isoformat())
            # Overruns never queue a burst. Other providers have separate clocks.
            if stamp(task['next_run_at']) <= now():
                task['next_run_at'] = (now()+dt.timedelta(seconds=self.interval)).isoformat()
            self.state['last_finished_at'] = task['finished_at']
            if all(t.get('status') in ('success','unconfigured') for t in self.state['tasks'].values()):
                self.state['last_success_at'] = task['finished_at']
            try:
                self._save()
            except Exception:
                self.storage_error = 'Не удалось сохранить состояние обновления.'
            finally:
                self.jobs.pop(key,None)

    def _current(self, source):
        from app import transtrade, neftm, rosneft, monitoring, catchup
        at = now(); start = at.date().replace(day=1).isoformat(); end = at.date().isoformat()
        if source!='monitoring':catchup.begin_read(self.folder,source,start,end,at=at)
        if source=='transtrade':
            result = transtrade.sync(self.folder,self.service.db_path,start,end,verify_days=False)
            count = result['received']
        elif source in ('neftm','rosneft'):
            result = {'neftm':neftm,'rosneft':rosneft}[source].sync(self.folder,start,end)
            count = len(result['rows'])
        else:
            result = monitoring.sync(self.folder)
            return dict(message=f"Обновлено {len(result['rows'])} объектов.")
        # A response crossing midnight must not certify a day still open when
        # the request began. The next cycle will read it as a completed day.
        catchup.mark_success(self.folder,source,start,end,at=at)
        return dict(message=f'Получено {count} записей за {start} — {end}.',received=count)

    def _history(self, source):
        from app import transtrade, neftm, rosneft, catchup
        if source == 'monitoring':
            return self._monitoring_history()
        job = catchup.plan(self.folder,self.service.db_path,source,today=now().date())
        with self.guard:
            previous=(self.state or {}).get('tasks',{}).get(source+':history',{})
            recent=stamp(previous.get('recent_checked_at'))
            if self.state is not None:
                previous.update(pending_days=job['pending_days'],**{'from':job['from'],'to':job['to']})
                self._save()
        recent_values={}
        if source!='transtrade' and (recent is None or now()-recent>=dt.timedelta(hours=24)
                                    or previous.get('recent_day')!=(now().date()-dt.timedelta(days=1)).isoformat()):
            # Fuel providers can publish completed-day readings late.
            end=now().date()-dt.timedelta(days=1)
            start=max(end-dt.timedelta(days=6),dt.date.fromisoformat(job['scope_start']))
            if start>end:
                return dict(message='Завершённых дней в выбранном охвате пока нет.',pending_days=0)
            {'neftm':neftm,'rosneft':rosneft}[source].sync(self.folder,start.isoformat(),end.isoformat())
            catchup.mark_success(self.folder,source,start.isoformat(),end.isoformat(),at=now())
            recent_values=dict(recent_checked_at=now().isoformat(),recent_day=end.isoformat())
            job = catchup.plan(self.folder,self.service.db_path,source,today=now().date())
        first,last = job['from'],job['to']
        if first:
            if source=='transtrade':
                transtrade.sync(self.folder,self.service.db_path,first,last,verify_days=False)
            else:
                {'neftm':neftm,'rosneft':rosneft}[source].sync(self.folder,first,last)
            catchup.mark_success(self.folder,source,first,last,at=now())
        after = catchup.plan(self.folder,self.service.db_path,source,today=now().date())
        message = f'Догружен период {first} — {last}.' if first else 'Пропущенных завершённых дней нет.'
        if source=='transtrade':
            result = transtrade.reconcile(self.folder,self.service.db_path)
            if result.get('status') in ('error','busy') or result.get('error'):
                raise ValueError(result.get('error') or 'Сверка истории ТТ ещё не завершена.')
            if result.get('status')=='success':
                message += f" История ТТ: {result['processed']} заявок."
        return dict(message=message,pending_days=after['pending_days'],**recent_values,**{'from':after['from'],'to':after['to']})

    def _monitoring_history(self):
        from app import catchup
        task = self.state['tasks']['monitoring:history']
        names = self.service.get_dataset()['vehicles']
        attempts = dict(task.get('day_attempts', {}))

        def plan():
            return catchup.plan(self.folder,self.service.db_path,'monitoring',today=now(),
                                names=names,monitoring_attempts=attempts)

        def checkpoint(queue, **fields):
            with self.guard:
                task.update(pending_days=queue['pending_days'], day_attempts=queue['monitoring_attempts'],
                            **{'from':queue['from'],'to':queue['to']}, **fields)
                self._save()

        queue = plan()
        attempts = queue['monitoring_attempts']
        checkpoint(queue)
        day = queue['from']
        yesterday = queue['target_end']
        checked = stamp(task.get('recent_checked_at')) if task.get('recent_day') == yesterday else None
        tried = stamp(task.get('recent_attempt_at')) if task.get('recent_attempt_day') == yesterday else None
        recheck = (queue['target_covered'] and (checked is None or now()-checked >= dt.timedelta(hours=6))
                   and (tried is None or now()-tried >= dt.timedelta(hours=1)))
        if recheck:
            # Persist before I/O so a failing late-data refresh cannot preempt
            # other dates every cycle, including after a worker restart.
            checkpoint(queue, recent_attempt_at=now().isoformat(), recent_attempt_day=yesterday)
            self._monitoring_day(names,yesterday,yesterday,refresh=True)
            checkpoint(queue, recent_checked_at=now().isoformat(), recent_day=yesterday)
        if day:
            try:
                self._monitoring_day(names,day,day,refresh=False)
            except IncompleteMonitoringDay:
                attempts[day] = now().isoformat()
                checkpoint(plan())
                raise
            catchup.mark_success(self.folder,'monitoring',day,day,at=now())
            queue = plan()
            checkpoint(queue, **(dict(recent_checked_at=now().isoformat(), recent_day=day) if day==yesterday else {}))
        message = (f'Догружена история за {day}.' if day else
                   'Ожидаем повторной попытки по пропущенным дням.' if queue['pending_days'] else
                   'Пропущенных завершённых дней нет.')
        return dict(message=message, pending_days=queue['pending_days'], **{'from':queue['from'],'to':queue['to']})

    def _monitoring_day(self,names,first,last,*,refresh):
        from app import monitoring_history
        current=monitoring_history.job_status(self.folder)
        if current and current['status']=='running':
            raise ValueError('История спутника уже загружается; догрузка повторится автоматически.')
        history=monitoring_history.start(self.folder,names,first,last,refresh=refresh)
        while not self.stop_event.wait(.25):
            current=monitoring_history.job_status(self.folder)
            if not current or current.get('id')!=history['id']:
                raise ValueError('Не подтверждено завершение истории спутника.')
            if current['status']!='running':break
        if self.stop_event.is_set():
            raise ValueError('Загрузка прервана остановкой; сохранённые порции будут использованы при продолжении.')
        if current.get('failure') == 'provider_access':
            # An account-wide failure is independent of the requested date.
            raise ValueError(current['message'])
        if current['status']!='complete':
            raise IncompleteMonitoringDay('Часть истории спутника пока не получена; загрузка продолжится автоматически.')

    def _beat(self):
        with self.guard:
            value = dict(at=now().isoformat(),pid=os.getpid(),status='stopping' if self.stop_event.is_set() else 'running',
                         jobs=copy.deepcopy(self.jobs))
            write_json(self.folder/HEARTBEAT,value)
            self.heartbeat_at = value['at']

    def _alerts(self):
        from app import alerts
        try:
            alerts.observe(self.folder,self.service.status(),deliver=True)
        except Exception:
            logger.error('Не удалось обновить журнал предупреждений.')

    def run(self):
        leader = self.service._lock('refresh-scheduler.lock')
        if not leader:
            return
        self.leader = True
        try:
            self._load()
            self._save()
            while not self.stop_event.is_set():
                try:
                    self._beat()
                    # Current data gets first chance before bounded historical work.
                    for source in NAMES:self._launch(source,'current')
                    for source in NAMES:self._launch(source,'history')
                    if time.monotonic()>=self.alert_due and not (self.alert_thread and self.alert_thread.is_alive()):
                        self.alert_thread=threading.Thread(target=self._alerts,daemon=True,name='fleet-alerts')
                        self.alert_thread.start();self.alert_due=time.monotonic()+30
                    with self.guard:
                        if self.storage_error:
                            self._save()
                            self.storage_error = None
                except Exception:
                    self.storage_error = 'Не удалось выполнить шаг планировщика; будет повторная попытка.'
                    logger.error(self.storage_error)
                self.stop_event.wait(1)
        finally:
            self.leader = False
            self.stop_event.set()
            try:self._beat()
            finally:leader.close()

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name='fleet-refresh-schedule')
        self.thread.start()

    def health(self):
        at = stamp(self.heartbeat_at)
        age = (now()-at).total_seconds() if at else None
        expired = any(stamp(x['deadline_at'])<now() for x in list(self.jobs.values()))
        dead = any(self.threads.get(key) and self.threads[key].ident is not None and not self.threads[key].is_alive() for key in list(self.jobs))
        healthy = bool(self.thread and self.thread.is_alive() and self.leader and at and age<45 and not expired and not dead and not self.storage_error)
        return dict(healthy=healthy,reason='Работает' if healthy else self.storage_error or 'Планировщик остановлен или задание не завершилось в срок.',
                    heartbeat_at=self.heartbeat_at,running=bool(self.jobs),scheduler_age_seconds=age)

    def stop(self,join_timeout=30):
        self.stop_event.set()
        deadline=time.monotonic()+join_timeout
        for thread in [self.thread,*list(self.threads.values()),self.alert_thread]:
            if thread and thread is not threading.current_thread():
                thread.join(max(0,deadline-time.monotonic()))
