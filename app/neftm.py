"""Read-only PWS transactions API. Credentials never leave the backend."""
import datetime as dt
import json
import os
import tempfile
import threading
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

import requests

URL = 'https://pws.neftm.ru/public-api/transactions.do'
FIELDS = ('amount','cardHolder','cardNumber','clientId','clientName','costClient',
          'currencyName','dateRec','posNum','priceClient','serviceName','terminalNum','typeNumber')
MAX_BYTES = 20 * 1024 * 1024
SYNC_LOCK = threading.Lock()


def period(start, end):
    try:
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except (ValueError, TypeError):
        raise ValueError('Укажите даты начала и конца периода.') from None
    if a > b or (b-a).days > 92:
        raise ValueError('Выберите период не длиннее 93 дней; дата начала должна быть раньше даты конца.')
    return a.isoformat(), b.isoformat()


def parse_transactions(content):
    if len(content) > MAX_BYTES or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('Некорректный XML-ответ Нефтьмагистрали.')
    try:
        root = ET.fromstring(content)
        if root.tag != 'transactions':
            raise ValueError()
        rows = []
        for node in root:
            if node.tag != 'transaction':
                raise ValueError()
            row = {key: node.findtext(key, default='') for key in FIELDS}
            if not row['dateRec'] or not row['typeNumber'] or not row['serviceName']:
                raise ValueError()
            dt.datetime.fromisoformat(row['dateRec'])
            for key in ('amount','costClient','priceClient'):
                if not Decimal(row[key]).is_finite():
                    raise ValueError()
            rows.append(row)
        return rows
    except (ET.ParseError, ValueError, InvalidOperation, TypeError):
        raise ValueError('Не удалось прочитать транзакции Нефтьмагистрали. Предыдущая загрузка сохранена.') from None


def write_json(path, body):
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(body, f, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def snapshot(data_dir):
    path = data_dir / 'neftm-transactions.json'
    return json.loads(path.read_text()) if path.exists() else None


def sync(data_dir, start, end):
    start, end = period(start, end)
    key_path = data_dir / 'neftm-api.key'
    if not key_path.exists() or not key_path.read_text().strip():
        raise ValueError('API-ключ Нефтьмагистрали не настроен на сервере.')
    if not SYNC_LOCK.acquire(blocking=False):
        raise ValueError('Обновление Нефтьмагистрали уже выполняется.')
    try:
        try:
            with requests.Session() as session:
                with session.post(URL, json={'token': key_path.read_text().strip(),
                    'dateFrom': start, 'dateTo': end, 'format': 'XML'},
                    timeout=(10,45), allow_redirects=False, stream=True) as response:
                    if response.status_code in (401,403):
                        raise ValueError('Нефтьмагистраль отклонила API-ключ. Предыдущая загрузка сохранена.')
                    if response.status_code != 200:
                        raise ValueError(f'Нефтьмагистраль вернула HTTP {response.status_code}. Предыдущая загрузка сохранена.')
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError('Ответ слишком большой. Уменьшите период загрузки.')
                        chunks.append(chunk)
                    rows = parse_transactions(b''.join(chunks))
        except requests.RequestException:
            raise ValueError('Нефтьмагистраль не ответила или соединение прервано. Повторите обновление позже; предыдущая загрузка сохранена.') from None
        result = {'provider':'neftm','from':start,'to':end,
                  'synced_at':dt.datetime.now(dt.timezone.utc).isoformat(),'rows':rows}
        # The API has no transaction ID: replace the requested snapshot, never append or deduplicate legitimate equal rows.
        from app.fuel_history import persist
        persist(data_dir,result)
        write_json(data_dir/'neftm-transactions.json', result)
        return result
    finally:
        SYNC_LOCK.release()
