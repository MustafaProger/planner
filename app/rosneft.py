"""Read-only RN-Card WebAPI; passwords are sent only in the documented header."""
import base64
import datetime as dt
import json
import threading
import uuid
from decimal import Decimal, InvalidOperation

import requests

from app.neftm import write_json

BASE = 'https://lkapi.rn-card.ru/api/emv/'
METHODS = {'v1/GetCardsByContract', 'v2/GetOperByContract'}
MAX_BYTES = 20 * 1024 * 1024
LOCK = threading.Lock()
TEXT_FIELDS = ('Date', 'Card', 'Contract', 'Address', 'GCode', 'GName', 'Holder',
               'Code', 'DTL', 'Ref', 'GCat', 'PosCode', 'CardGrp', 'PosCoord', 'Rrn')
NUMBER_FIELDS = ('Value', 'Sum', 'DSum', 'Price', 'DPrice', 'Vat')


def configured(data_dir):
    return (data_dir / 'rosneft-credentials.json').is_file()


def snapshot(data_dir):
    path = data_dir / 'rosneft-transactions.json'
    return json.loads(path.read_text()) if path.exists() else None


def period(start, end):
    try:
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        if not 0 <= (b - a).days <= 30:
            raise ValueError()
        return a.isoformat(), b.isoformat()
    except (TypeError, ValueError):
        raise ValueError('Выберите период от 1 до 31 дня.') from None


def read(session, credentials, method, **params):
    if method not in METHODS:
        raise ValueError('Метод Роснефти не разрешён для чтения.')
    try:
        with session.get(BASE + method,
                params={'u': credentials['login'], 'contract': credentials['contract'],
                        'type': 'json', **params},
                headers={'RnCard-Identity-Account-Pass': base64.b64encode(
                    credentials['password'].encode('utf-8')).decode('ascii'),
                    'RnCard-RequestId': str(uuid.uuid4())},
                timeout=(10, 45), allow_redirects=False, stream=True) as response:
            if response.status_code in (401, 403):
                raise ValueError('Роснефть отклонила доступ к API. Проверьте пароль, доступ договора и разрешённые IP. Предыдущая загрузка сохранена.')
            if response.status_code == 429:
                raise ValueError('Роснефть ограничила частоту запросов. Повторите позже; предыдущая загрузка сохранена.')
            if response.status_code != 200:
                raise ValueError(f'Роснефть вернула HTTP {response.status_code}. Предыдущая загрузка сохранена.')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Ответ Роснефти слишком большой. Уменьшите период; предыдущая загрузка сохранена.')
                chunks.append(chunk)
            try:
                return json.loads(b''.join(chunks), parse_float=Decimal)
            except (ValueError, UnicodeError):
                raise ValueError('Некорректный ответ Роснефти. Предыдущая загрузка сохранена.') from None
    except requests.RequestException:
        # Never propagate a request URL, headers or upstream response containing credentials.
        raise ValueError('Соединение с Роснефтью прервано. Повторите позже; предыдущая загрузка сохранена.') from None


def normalize(cards, operations, contract, start, end):
    try:
        if not isinstance(cards, list) or not isinstance(operations, dict):
            raise ValueError()
        card_rows, card_ids = [], set()
        for card in cards:
            if not isinstance(card, dict) or not isinstance(card.get('Num'), str) or not card['Num'] or card['Num'] in card_ids:
                raise ValueError()
            card_ids.add(card['Num'])
            card_rows.append({key: str(card.get(key) or '') for key in ('Num', 'Rem', 'SName', 'SCode', 'CardGrp')})
        source = operations.get('OperationList')
        if not isinstance(source, list):
            raise ValueError()
        rows, ids = [], set()
        for op in source:
            if not isinstance(op, dict) or op.get('Contract') != contract:
                raise ValueError()
            if not isinstance(op.get('Code'), str) or not op['Code'] or op['Code'] in ids:
                raise ValueError()
            ids.add(op['Code'])
            if not isinstance(op.get('Card'), str) or type(op.get('Type')) is not int:
                raise ValueError()
            # Provider dates are terminal-local wall time; do not convert them to Moscow or UTC.
            date = dt.datetime.fromisoformat(op['Date'])
            if not start <= date.date().isoformat() <= end:
                raise ValueError()
            row = {key: str(op.get(key) or '') for key in TEXT_FIELDS}
            row['Type'] = op['Type']
            for key in NUMBER_FIELDS:
                value = op.get(key)
                if value is None and key == 'Vat':
                    row[key] = ''
                    continue
                number = Decimal(str(value))
                if not number.is_finite():
                    raise ValueError()
                row[key] = str(number)
            row['NetSum'] = str(Decimal(row['Sum']) - Decimal(row['DSum'])) if row['Type'] in (11, 24) else ''
            rows.append(row)
        return card_rows, sorted(rows, key=lambda row: (row['Date'], row['Code']), reverse=True)
    except (ValueError, TypeError, KeyError, InvalidOperation):
        raise ValueError('Не удалось проверить данные Роснефти. Предыдущая загрузка сохранена.') from None


def sync(data_dir, start, end):
    start, end = period(start, end)
    if not LOCK.acquire(blocking=False):
        raise ValueError('Обновление Роснефти уже выполняется.')
    try:
        try:
            credentials = json.loads((data_dir / 'rosneft-credentials.json').read_text())
            if not all(isinstance(credentials.get(key), str) and credentials[key] for key in ('login', 'password', 'contract')):
                raise ValueError()
        except (OSError, ValueError, AttributeError):
            raise ValueError('Доступ к Роснефти не настроен на сервере.') from None
        with requests.Session() as session:
            cards = read(session, credentials, 'v1/GetCardsByContract')
            operations = read(session, credentials, 'v2/GetOperByContract',
                              begin=start + 'T00:00:00', end=end + 'T23:59:59')
        cards, rows = normalize(cards, operations, credentials['contract'], start, end)
        result = {'provider': 'rosneft', 'contract': credentials['contract'],
                  'from': start, 'to': end, 'synced_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'cards': cards, 'rows': rows}
        # A complete snapshot replaces the preceding period. Failed/partial loads never replace it.
        from app.fuel_history import persist
        persist(data_dir,result)
        write_json(data_dir / 'rosneft-transactions.json', result)
        return result
    finally:
        LOCK.release()
