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


def test_no_signin_observation_is_not_a_success(tmp_path):
    rows=[{'id':'axenta','status':'Соединение не проверено','network':'HTTP 200'}]
    assert with_authorization(rows,tmp_path)==rows
