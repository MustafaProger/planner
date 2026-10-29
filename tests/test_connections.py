import json
from app.connections import with_authorization


def test_network_probe_does_not_erase_signin_result(tmp_path):
    observations={'neftm': {'status': 'Вход подтверждён · без синхронизации',
                          'detail': 'Отчёт ещё не загружен.', 'checked_at': '27.10.2026 11:10 МСК'}}
    (tmp_path/'connections-auth.json').write_text(json.dumps(observations))
    network=[{'id':'neftm','status':'Нет соединения','detail':'Timeout','network':'Timeout',
              'checked_at':'27.10.2026 11:20 МСК'},
             {'id':'transtrade','status':'Нужен API-доступ'}]
    rows=with_authorization(network,tmp_path)
    assert rows[0]['status']==observations['neftm']['status']
    assert rows[0]['checked_at']=='27.10.2026 11:20 МСК'
    assert rows[0]['authorization_checked_at']=='27.10.2026 11:10 МСК'
    assert 'Timeout' in rows[0]['detail'] and 'Отчёт ещё не загружен' in rows[0]['detail']
    assert network[0]['status']=='Нет соединения'
    assert rows[1]==network[1]
    assert with_authorization(rows,tmp_path)==rows


def test_rosneft_live_snapshot_supersedes_old_login_failure(tmp_path):
    (tmp_path/'connections-auth.json').write_text(json.dumps({'rosneft':{'status':'Доступ отклонён','detail':'old','checked_at':'old'}}))
    (tmp_path/'rosneft-transactions.json').write_text(json.dumps({'rows':[{}],'cards':[{}],'from':'2026-08-01','to':'2026-08-31','synced_at':'2026-10-28T10:00:00+00:00'}))
    result=with_authorization([{'id':'rosneft'}],tmp_path)[0]
    assert result['status']=='API подключён' and '1 операций' in result['detail']
    assert result['authorization_checked_at']=='28.10.2026 13:00 МСК'

def test_no_signin_observation_is_not_a_success(tmp_path):
    rows=[{'id':'monitoring','status':'Соединение не проверено','network':'HTTP 200'}]
    assert with_authorization(rows,tmp_path)==rows


def test_legacy_axenta_failure_is_not_used_for_monitoring(tmp_path):
    (tmp_path/'connections-auth.json').write_text(json.dumps({'axenta':{'status':'Неверный пароль','detail':'Wrong host','checked_at':'old'}}))
    rows=with_authorization([{'id':'axenta','network':'HTTP 401'}],tmp_path)
    assert rows[0]['id']=='monitoring'
    assert 'network' not in rows[0]
    assert rows[0]['status']=='Соединение не проверено'
    assert rows[0]['url'].startswith('https://glonasssoft.ru/')
