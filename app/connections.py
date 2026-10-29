"""Read-only connectivity diagnostics. No credentials transmitted to an unverified endpoint."""
import concurrent.futures, datetime as dt, json
import requests
SOURCES=[
 dict(id='transtrade',name='ТрансТрейд',url='https://tt-ok.ru/data/api_doc/',probe='https://tt-ok.ru/data/api_doc/',status='Соединение не проверено',detail='Загрузка заявок по API выполняется руководителем за выбранный период. Реквизиты хранятся только на сервере.'),
 dict(id='monitoring',name='Мониторинг · ГЛОНАССсофт',url='https://glonasssoft.ru/wiki/metody-api-dlya-raboty-s-glonasssoft',probe='https://monitoringtransporta.online/',status='Соединение не проверено',detail='Сервер monitoringtransporta.online. Токен выдаётся через POST /api/v3/auth/login; отдельное создание ключа в кабинете не требуется.'),
 dict(id='rosneft',name='Роснефть · РН-Карт',url='https://lk.rn-card.ru/Faq',probe='https://lk.rn-card.ru/Users/ReLogin.aspx',status='Соединение не проверено',detail='Логин и пароль предоставлены. Документация API доступна в разделе «Инструкции» кабинета; доступ к API предоставляется по заявке. Наличие API-доступа у этой учётной записи не подтверждено.'),
 dict(id='neftm',name='Нефтьмагистраль',url='https://pws.neftm.ru/pws/login.do',probe='https://pws.neftm.ru/pws/login.do',status='Соединение не проверено',detail='Логин и пароль предоставлены. Авторизация, схема API и топливные операции ещё не получены.'),
]
def probe(source):
    r=dict(source);r.pop('probe');r['checked_at']=dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')
    try:
        with requests.get(source['probe'],timeout=(5,8),allow_redirects=False,stream=True) as response:
            r['network']=f'HTTP {response.status_code}'
            r['detail']+=f' Проверка сети: HTTP {response.status_code}. Это не проверка учётных данных.'
    except requests.exceptions.SSLError:
        r['network']='TLS error';r['detail']+=' Проверка сети: ошибка проверки сертификата TLS. Проверка сертификата не отключалась.'
    except requests.exceptions.Timeout:
        r['network']='Timeout';r['detail']+=' Проверка сети: сервер не ответил вовремя. Пароль не отправлялся.'
    except requests.exceptions.RequestException:
        r['network']='Network error';r['detail']+=' Проверка сети: соединение не установлено. Пароль не отправлялся.'
    if r.get('network') in ('Timeout','Network error','TLS error'):r['status']='Нет соединения' if source['id']!='transtrade' else 'Нет соединения'
    return r

def check_all():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return list(pool.map(probe,SOURCES))


def with_authorization(results, data_dir):
    """Keep observed sign-in results separate from unauthenticated network probes."""
    path = data_dir / 'connections-auth.json'
    observations = json.loads(path.read_text()) if path.exists() else {}
    from app.neftm import snapshot
    live = snapshot(data_dir)
    if live:
        observations['neftm'] = {'status':'API подключён',
            'detail':f"Получено {len(live['rows'])} транзакций за {live['from']} — {live['to']}. Обновление доступно руководителю в таблице ниже.",
            'checked_at':dt.datetime.fromisoformat(live['synced_at']).astimezone(dt.timezone(dt.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')}
    from app.monitoring import snapshot as monitoring_snapshot
    monitoring = monitoring_snapshot(data_dir)
    if monitoring:
        observations['monitoring'] = {'status':'API подключён',
            'detail':f"Получены {len(monitoring['rows'])} объектов и последние показания с monitoringtransporta.online. История пробега, моточасов и топлива загружается на странице подключения и включается в расчёты по мере получения.",
            'checked_at':dt.datetime.fromisoformat(monitoring['synced_at']).astimezone(dt.timezone(dt.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')}
    from app.rosneft import snapshot as rosneft_snapshot
    rosneft = rosneft_snapshot(data_dir)
    if rosneft:
        observations['rosneft'] = {'status': 'API подключён',
            'detail': f"Получено {len(rosneft['rows'])} операций за {rosneft['from']} — {rosneft['to']} и {len(rosneft['cards'])} карт. Обновление по кнопке доступно руководителю. Время операций — местное время терминала; данные провайдера могут запаздывать до двух часов.",
            'checked_at': dt.datetime.fromisoformat(rosneft['synced_at']).astimezone(dt.timezone(dt.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')}
    from app.transtrade import configured, status as tt_status
    import sqlite3
    if configured(data_dir):
        with sqlite3.connect(data_dir/'fleet.sqlite') as c:
            tt=tt_status(c)
        detail='API-реквизиты настроены; выполните загрузку заявок для проверки.'
        label='Готов к проверке'
        if tt:
            label='API подключён' if tt['status']=='success' else 'Ошибка обновления'
            detail=(f"Последняя успешная загрузка: {tt.get('start','—')} — {tt.get('end','—')}, {tt.get('received',0)} заявок. " if tt.get('synced_at') else '')+tt.get('error','')+' '+tt.get('limitations','')
        observations['transtrade']=dict(status=label,detail=detail,checked_at=(tt or {}).get('attempted_at',(tt or {}).get('synced_at','Не проверено')))
    merged = []
    for source in results:
        row = dict(source)
        if row['id']=='axenta':
            # Old cache describes a different host: discard that network/sign-in result.
            row = {k:v for k,v in next(s for s in SOURCES if s['id']=='monitoring').items() if k!='probe'}
        observation = observations.get(row['id'])
        if observation:
            row['status'] = observation['status']
            row['detail'] = observation['detail']
            row['authorization_checked_at'] = observation['checked_at']
            row['detail'] += ' Проверка доступа: ' + observation['checked_at'] + '.'
            if row.get('network'):
                row['detail'] += ' Последняя проверка сети: ' + row['network'] + '. Она не проверяет пароль или синхронизацию.'
        merged.append(row)
    return merged
