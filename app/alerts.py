"""Durable, quiet incident reporting for unattended source refresh.

Only fixed operational messages leave this module. Provider messages, account
data and notification credentials never enter incident records or responses.
Outbound delivery is disabled until explicitly configured by the administrator.
"""
import datetime as dt
import fcntl
import json
import os
import re
import smtplib
import ssl
import tempfile
import uuid
from email.message import EmailMessage
from pathlib import Path

import requests


SOURCE_NAMES = {'transtrade': 'ТрансТрейд', 'neftm': 'Нефтьмагистраль',
                'rosneft': 'Роснефть', 'monitoring': 'ГЛОНАССсофт'}
UTC = dt.timezone.utc
STATE_NAME = 'alerts-state.json'
CONFIG_NAME = 'alerts-config.json'
DEFAULT_STALE_SECONDS = 900
DEFAULT_HEARTBEAT_SECONDS = 90
MAX_RECENT = 50
DELIVERY_ERROR = 'Предупреждение пока не доставлено. Приложение повторит попытку.'
CONFIG_ERROR = 'Настройка внешних уведомлений некорректна. Сообщения наружу не отправляются.'
STORAGE_ERROR = 'Журнал предупреждений недоступен или повреждён. Проверьте хранилище приложения.'


def _time(value=None):
    if value is None:
        return dt.datetime.now(UTC)
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            pass
    return None


def _age(now, value):
    stamp = _time(value) if value is not None else None
    return max(0, (now-stamp).total_seconds()) if stamp else None


def _number(value, default, minimum, maximum):
    return value if type(value) is int and minimum <= value <= maximum else default


def _config(data_dir):
    path = Path(data_dir)/CONFIG_NAME
    try:
        config = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(config, dict):
            raise ValueError()
        if config.get('enabled') is True and path.stat().st_mode & 0o077:
            raise ValueError()  # Never send using a shared-readable secret file.
        config['stale_after_seconds'] = _number(config.get('stale_after_seconds'), DEFAULT_STALE_SECONDS, 300, 604800)
        config['heartbeat_stale_seconds'] = _number(config.get('heartbeat_stale_seconds'), DEFAULT_HEARTBEAT_SECONDS, 15, 3600)
        config['retry_seconds'] = _number(config.get('retry_seconds'), 60, 30, 3600)
        config['enabled'] = config.get('enabled') is True
        if config['enabled'] and config.get('channel') not in ('smtp', 'telegram'):
            raise ValueError()
        return config, None
    except (OSError, ValueError, TypeError):
        return {'enabled': False, 'stale_after_seconds': DEFAULT_STALE_SECONDS,
                'heartbeat_stale_seconds': DEFAULT_HEARTBEAT_SECONDS, 'retry_seconds': 60}, CONFIG_ERROR


def _empty():
    return {'version': 1, 'conditions': {}, 'active': {}, 'recent': [], 'outbox': [], 'delivery': {}}


def _load(data_dir):
    path = Path(data_dir)/STATE_NAME
    try:
        if not path.exists():
            return _empty(), None
        value = json.loads(path.read_text())
        if (not isinstance(value, dict) or value.get('version') != 1
                or any(not isinstance(value.get(k), dict) for k in ('conditions', 'active', 'delivery'))
                or any(not isinstance(value.get(k), list) for k in ('recent', 'outbox'))
                or any(not isinstance(item, dict) for k in ('conditions', 'active') for item in value[k].values())
                or any(not isinstance(item, dict) for k in ('recent', 'outbox') for item in value[k])
                or any(not all(isinstance(item.get(k), str) for k in ('id', 'key', 'title', 'message'))
                       for item in [*value['active'].values(), *value['recent']])
                or any(not all(isinstance(item.get(k), str) for k in ('id', 'incident_id', 'event', 'text'))
                       or type(item.get('attempts')) is not int for item in value['outbox'])):
            raise ValueError()
        return value, None
    except (OSError, ValueError, TypeError):
        # Preserve damaged state for diagnosis; resetting would resend incidents.
        return _empty(), STORAGE_ERROR


def _save(data_dir, state):
    folder = Path(data_dir)
    fd, temporary = tempfile.mkstemp(prefix='.alerts-', dir=folder)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(state, output, ensure_ascii=False, separators=(',', ':'))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, folder/STATE_NAME)
        directory = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _since(source, previous, status, now):
    for value in (previous.get('first_seen'), source.get('error_since'), source.get('started_at'),
                  source.get('last_attempt_at'), status.get('started_at')):
        stamp = _time(value) if value is not None else None
        if stamp and stamp <= now:
            return stamp
    return now


def _conditions(status, state, config, now):
    """Return candidate conditions, including those still in the grace period."""
    conditions = {}
    for key, label in SOURCE_NAMES.items():
        source = status.get('sources', {}).get(key)
        name = 'source:'+key
        if not isinstance(source, dict):
            # A partial status payload is not evidence that an incident healed.
            if name in state.get('active', {}):
                conditions[name] = dict(state['active'][name], eligible=True)
            continue
        if source.get('status') == 'unconfigured' or source.get('configured') is False:
            continue
        previous = state.get('conditions', {}).get(name, {})
        last = source.get('last_success_at')
        age = _age(now, last)
        failed = source.get('status') in ('error', 'interrupted', 'failed')
        if not failed and age is not None and age < config['stale_after_seconds']:
            continue
        since = _since(source, previous, status, now)
        # A preserved old success proves stale data immediately, even after a
        # worker restart; repeated attempts must not reset the failure timer.
        eligible = ((age is not None and age >= config['stale_after_seconds'])
                    or (now-since).total_seconds() >= config['stale_after_seconds'])
        conditions[name] = {'key': name, 'source': key, 'severity': 'warning',
            'title': label+': обновление задерживается',
            'message': ('Обновление источника долго не завершается успешно. Прежние записи сохранены; '
                        'приложение продолжает попытки. Проверьте доступность источника и подключения.'),
            'first_seen': since.isoformat(), 'eligible': eligible,
            'last_success_at': _time(last).isoformat() if last and _time(last) else None}
    if status.get('scheduler_expected', True):
        heartbeat = status.get('heartbeat_at')
        age = _age(now, heartbeat)
        if not status.get('server_scheduler', False) or age is None or age >= config['heartbeat_stale_seconds']:
            previous = state.get('conditions', {}).get('worker', {})
            since = _since({}, previous, status, now)
            if heartbeat and _time(heartbeat):
                since = min(since, _time(heartbeat))
            conditions['worker'] = {'key': 'worker', 'source': None, 'severity': 'error',
                'title': 'Автоматическое обновление остановилось',
                'message': ('Давно нет сигнала от фонового обновления. Сайт может открываться с прежними данными. '
                            'Проверьте службу обновления на сервере.'),
                'first_seen': since.isoformat(),
                'eligible': (now-since).total_seconds() >= config['heartbeat_stale_seconds'],
                'last_success_at': None}
    return conditions


def _public(incident):
    return {k: incident.get(k) for k in ('id', 'key', 'source', 'severity', 'title', 'message',
            'first_seen', 'opened_at', 'last_seen', 'last_success_at', 'resolved_at', 'status')}


def _backlog(status):
    result = []
    for key, label in SOURCE_NAMES.items():
        source = status.get('sources', {}).get(key, {})
        catchup = source.get('catchup') or {}
        if not isinstance(catchup, dict):
            continue
        pending = catchup.get('pending_days', 0)
        if type(pending) is int and pending > 0:
            result.append({'source': key, 'name': label, 'pending_days': pending,
                           'message': f'Догружаются пропущенные данные: {pending} дн.'})
    return result


def _view(status, state, config, config_error, storage_error, now):
    conditions = _conditions(status, state, config, now)
    active = []
    for key, condition in conditions.items():
        if condition['eligible']:
            item = dict(condition, status='open', last_seen=now.isoformat())
            item.update(state['active'].get(key, {}))
            active.append(_public(item))
    delivery = dict(state.get('delivery', {}))
    delivery.update(configured=config['enabled'], channel=config.get('channel') if config['enabled'] else None,
                    pending=len(state.get('outbox', [])))
    if config_error or storage_error:
        delivery.update(status='error', error=config_error or storage_error)
    elif not config['enabled']:
        delivery.pop('error', None)
        delivery.update(status='disabled', message='Внешние уведомления не настроены; предупреждения видны в приложении.')
    else:
        delivery.setdefault('status', 'ready')
    return {'incidents': sorted(active, key=lambda row: (row['severity'] != 'error', row['key'])),
            'recent': [_public(x) for x in state['recent'][-MAX_RECENT:][::-1]],
            'backlog': _backlog(status), 'delivery': delivery,
            'storage_error': storage_error, 'checked_at': now.isoformat()}


def current(data_dir, status, *, at=None):
    """Read-only view also derives stale-worker warnings when the worker is dead."""
    config, config_error = _config(data_dir)
    state, storage_error = _load(data_dir)
    return _view(status, state, config, config_error, storage_error, _time(at))


def _queue(state, incident, event, now):
    ident = incident['id']+':'+event
    # Never send an old recovery after the same source has failed again.
    state['outbox'] = [item for item in state['outbox']
                       if item.get('key') != incident['key'] or item['incident_id'] == incident['id']]
    if any(item['id'] == ident for item in state['outbox']):
        return
    recovered = event == 'recovered'
    source = SOURCE_NAMES.get(incident.get('source'), 'Автоматическое обновление')
    text = (f'Логистика: {source}. Обновление восстановлено.' if recovered else
            'Логистика: '+incident['title']+'. '+incident['message'])
    text += '\nВремя: '+now.astimezone(dt.timezone(dt.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')
    state['outbox'].append({'id': ident, 'key': incident['key'], 'incident_id': incident['id'], 'event': event,
                           'text': text, 'attempts': 0, 'next_attempt_at': now.isoformat()})


def _secret(values, key):
    env_name = values.get(key+'_env')
    if env_name is not None:
        if not isinstance(env_name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env_name):
            raise ValueError(CONFIG_ERROR)
        return os.environ.get(env_name, '')
    return values.get(key, '')


def _send(config, text):
    """Never propagate remote bodies/errors, which can contain credentials."""
    if config['channel'] == 'telegram':
        values = config.get('telegram', {})
        token, chat = _secret(values, 'bot_token'), values.get('chat_id')
        if not isinstance(token, str) or not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token) or not isinstance(chat, (str, int)) or not str(chat):
            raise ValueError(CONFIG_ERROR)
        response = requests.post('https://api.telegram.org/bot'+token+'/sendMessage',
            json={'chat_id': chat, 'text': text, 'disable_web_page_preview': True},
            timeout=(5, 10), allow_redirects=False)
        try:
            if response.status_code != 200 or response.json().get('ok') is not True:
                raise ValueError(DELIVERY_ERROR)
        finally:
            response.close()
    elif config['channel'] == 'smtp':
        values = config.get('smtp', {})
        host, sender, recipients = values.get('host'), values.get('from'), values.get('to')
        security = values.get('security', 'ssl')
        port = values.get('port', 465 if security == 'ssl' else 587)
        if (not isinstance(host, str) or not host or security not in ('ssl', 'starttls')
                or type(port) is not int or not 1 <= port <= 65535
                or not isinstance(sender, str) or not sender or '\n' in sender or '\r' in sender
                or not isinstance(recipients, list) or not recipients
                or any(not isinstance(x, str) or not x or '\n' in x or '\r' in x for x in recipients)):
            raise ValueError(CONFIG_ERROR)
        message = EmailMessage()
        message['Subject'] = 'Логистика — состояние обновления данных'
        message['From'], message['To'] = sender, ', '.join(recipients)
        message.set_content(text)
        context = ssl.create_default_context()
        smtp = (smtplib.SMTP_SSL(host, port, timeout=10, context=context) if security == 'ssl'
                else smtplib.SMTP(host, port, timeout=10))
        with smtp:
            if security == 'starttls':
                smtp.ehlo();smtp.starttls(context=context);smtp.ehlo()
            if values.get('username'):
                smtp.login(values['username'], _secret(values, 'password'))
            smtp.send_message(message, from_addr=sender, to_addrs=recipients)
    else:
        raise ValueError(CONFIG_ERROR)


def observe(data_dir, status, *, at=None, deliver=True):
    """Persist transitions, then attempt at most one queued external notification.

    Call outside the critical scheduler heartbeat path: external delivery may
    take network timeout time. The cross-process lock prevents duplicate sends.
    """
    now = _time(at)
    config, config_error = _config(data_dir)
    lock_path = Path(data_dir)/'alerts.lock'
    with lock_path.open('a') as lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return current(data_dir, status, at=now)
        state, storage_error = _load(data_dir)
        if storage_error:
            return _view(status, state, config, config_error, storage_error, now)
        conditions = _conditions(status, state, config, now)
        for key, active in list(state['active'].items()):
            condition = conditions.get(key)
            if condition and condition['eligible']:
                active.update(last_seen=now.isoformat(), last_success_at=condition['last_success_at'])
                continue
            source = status.get('sources', {}).get(active.get('source'), {})
            disabled = source.get('status') == 'unconfigured' or source.get('configured') is False
            active.update(status='closed' if disabled else 'resolved', resolved_at=now.isoformat(), last_seen=now.isoformat())
            if disabled:
                active['message'] = 'Предупреждение закрыто: источник больше не подключён.'
            state['recent'].append(active)
            state['outbox'] = [item for item in state['outbox'] if item['incident_id'] != active['id']]
            if config['enabled'] and active.get('notification_sent') and not disabled:
                _queue(state, active, 'recovered', now)
            del state['active'][key]
        for key, condition in conditions.items():
            if not condition['eligible']:
                continue
            if key not in state['active']:
                incident = {k: v for k, v in condition.items() if k != 'eligible'}
                incident.update(id=uuid.uuid4().hex, status='open', opened_at=now.isoformat(),
                                last_seen=now.isoformat(), notification_sent=False)
                state['active'][key] = incident
            active = state['active'][key]
            if config['enabled'] and not active.get('notification_sent'):
                _queue(state, active, 'opened', now)
        state['conditions'] = {key: {'first_seen': item['first_seen']} for key, item in conditions.items()}
        state['recent'] = state['recent'][-MAX_RECENT:]
        state['updated_at'] = now.isoformat()
        if not config['enabled']:
            state['outbox'] = []
        if not state['outbox'] and state['delivery'].get('status') == 'error':
            state['delivery'].update(status='ready')
            state['delivery'].pop('error', None)
        _save(data_dir, state)  # Durable intent before any network effect.
        ready = [item for item in state['outbox'] if (_time(item.get('next_attempt_at')) or now) <= now]
        if config['enabled'] and deliver and ready:
            item = ready[0]
            try:
                _send(config, item['text'])
            except Exception:
                item['attempts'] += 1
                retry = min(3600, config['retry_seconds'] * 2**min(item['attempts']-1, 10))
                item['next_attempt_at'] = (now+dt.timedelta(seconds=retry)).isoformat()
                state['delivery'].update(status='error', error=DELIVERY_ERROR, last_attempt_at=now.isoformat())
            else:
                state['outbox'].remove(item)
                for incident in state['active'].values():
                    if incident['id'] == item['incident_id'] and item['event'] == 'opened':
                        incident['notification_sent'] = True
                state['delivery'] = {'status': 'sent', 'last_success_at': now.isoformat(), 'last_attempt_at': now.isoformat()}
            _save(data_dir, state)
        return _view(status, state, config, config_error, storage_error, now)
