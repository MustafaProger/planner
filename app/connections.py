"""Read-only connectivity diagnostics. No credentials transmitted to an unverified endpoint."""
import concurrent.futures, datetime as dt, json
import requests
SOURCES=[
 dict(id='transtrade',name='ТрансТрейд',url='https://tt-ok.ru/data/api_doc/',probe='https://tt-net.ru/',status='Нужен API-доступ',detail='Предоставлены логин и пароль. Для документированного API нужны API KEY и api_user_id; в файле доступов их нет. Excel-выгрузка импортирована.'),
 dict(id='axenta',name='AXENTA · спутниковый мониторинг',url='https://docs.axenta.tech/docs/api/',probe='https://axenta.cloud/',status='Соединение не проверено',detail='Провайдер подтверждён пользователем. Есть логин и пароль. Официальный вход axenta.cloud; API опубликован в /api-docs/. Авторизация и получение отчётов ещё не подтверждены.'),
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
    if r.get('network') in ('Timeout','Network error','TLS error'):r['status']='Нет соединения' if source['id']!='transtrade' else 'Нужен API-доступ'
    return r

def check_all():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return list(pool.map(probe,SOURCES))
