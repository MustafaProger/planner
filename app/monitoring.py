"""Read-only GLONASSsoft V3 connector for the customer's own server."""
import datetime as dt
import json
import threading
import time

import requests

from app.neftm import write_json

BASE = 'https://monitoringtransporta.online/api/v3/'
DOCS = 'https://glonasssoft.ru/wiki/metody-api-dlya-raboty-s-glonasssoft'
LOCK = threading.Lock()
MAX_BYTES = 20 * 1024 * 1024
READ_METHODS = {'vehicles/find', 'vehicles/getlastdata',
                'vehicles/mileageAndMotohours', 'vehicles/fuelConsumption'}
VEHICLE_FIELDS = ('vehicleId', 'vehicleGuid', 'name', 'modelName', 'status')
LATEST_FIELDS = ('recordTime', 'receiveTime', 'state', 'speed')


class AuthenticationError(ValueError):
    pass


class RateLimitError(ValueError):
    pass


def snapshot(data_dir):
    path = data_dir / 'monitoring-vehicles.json'
    return json.loads(path.read_text()) if path.exists() else None


def configured(data_dir):
    return (data_dir / 'monitoring-credentials.json').exists()


class Client:
    def __init__(self, data_dir, session):
        self.data_dir, self.session = data_dir, session
        token = data_dir / 'monitoring-session.json'
        self.token = json.loads(token.read_text()) if token.exists() else ''
        self.last_request = 0

    def request(self, method, body, token=''):
        time.sleep(max(0, 1.1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        try:
            with self.session.post(BASE + method, json=body,
                    headers={'X-Auth': token} if token else {},
                    timeout=(10, 45), allow_redirects=False, stream=True) as response:
                if response.status_code == 401:
                    return 401, None
                if response.status_code == 403:
                    raise AuthenticationError('Мониторинг запретил доступ к этим данным.')
                if response.status_code == 429:
                    raise RateLimitError('Мониторинг ограничил частоту запросов. Продолжите загрузку позже.')
                if response.status_code != 200:
                    raise ValueError(f'Мониторинг вернул HTTP {response.status_code}. Предыдущая загрузка сохранена.')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError('Ответ мониторинга слишком большой. Предыдущая загрузка сохранена.')
                    chunks.append(chunk)
                try:
                    return 200, json.loads(b''.join(chunks))
                except (ValueError, UnicodeError):
                    raise ValueError('Некорректный ответ мониторинга. Предыдущая загрузка сохранена.') from None
        except requests.RequestException:
            raise ValueError('Мониторинг не ответил или соединение прервано. Предыдущая загрузка сохранена.') from None

    def login(self):
        path = self.data_dir / 'monitoring-credentials.json'
        if not path.exists():
            raise ValueError('Доступ к мониторингу не настроен на сервере.')
        credentials = json.loads(path.read_text())
        _, body = self.request('auth/login', {key: credentials[key] for key in ('login', 'password')})
        if not isinstance(body, dict) or not isinstance(body.get('AuthId'), str) or not body['AuthId']:
            # Never include upstream error text, credentials or response bodies in logs/UI.
            raise AuthenticationError('Мониторинг не выдал токен авторизации. Проверьте доступ в кабинете; предыдущая загрузка сохранена.')
        if body.get('IsSecondAuthFactorCodeRequired') or body.get('IsUserDeviceAccessDenied'):
            raise AuthenticationError('Требуется подтверждение входа в кабинете мониторинга.')
        self.token = body['AuthId']
        # Atomic private file, same helper as data snapshots; token is stored as a JSON string.
        write_json(self.data_dir / 'monitoring-session.json', self.token)

    def read(self, method, body):
        if method not in READ_METHODS:
            raise ValueError('Метод не разрешён для чтения.')
        if not self.token:
            self.login()
        status, result = self.request(method, body, self.token)
        if status == 401:
            self.login()
            status, result = self.request(method, body, self.token)
        if status == 401:
            raise AuthenticationError('Мониторинг отклонил сессию. Проверьте доступ в кабинете.')
        if status != 200 or not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
            raise ValueError('Мониторинг не вернул список данных. Предыдущая загрузка сохранена.')
        return result


def normalize(vehicles, latest):
    ids = [v.get('vehicleId') for v in vehicles]
    if any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Некорректный список объектов мониторинга. Предыдущая загрузка сохранена.')
    latest_ids = [v.get('vehicleId') for v in latest]
    if any(type(i) is not int or i not in ids for i in latest_ids) or len(set(latest_ids)) != len(latest_ids):
        raise ValueError('Некорректные последние показания мониторинга. Предыдущая загрузка сохранена.')
    by_id = {v['vehicleId']: v for v in latest}
    return [{**{key: v.get(key) for key in VEHICLE_FIELDS},
             **{key: by_id.get(v['vehicleId'], {}).get(key) for key in LATEST_FIELDS}}
            for v in vehicles]


def sync(data_dir):
    if not LOCK.acquire(blocking=False):
        raise ValueError('Обновление мониторинга уже выполняется.')
    try:
        with requests.Session() as session:
            client = Client(data_dir, session)
            vehicles = client.read('vehicles/find', {})
            # Validate IDs before sending a second request.
            normalize(vehicles, [])
            latest = client.read('vehicles/getlastdata', {
                'vehiclesIds': [v['vehicleId'] for v in vehicles], 'includeSensors': False
            }) if vehicles else []
        result = {'provider': 'monitoring', 'server': 'https://monitoringtransporta.online',
                  'synced_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'rows': normalize(vehicles, latest)}
        write_json(data_dir / 'monitoring-vehicles.json', result)
        return result
    finally:
        LOCK.release()
