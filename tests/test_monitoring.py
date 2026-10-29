import json
from unittest.mock import Mock

import pytest
import requests

from app import monitoring as m


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield json.dumps(self.body).encode()


@pytest.fixture
def configured(tmp_path, monkeypatch):
    (tmp_path/'monitoring-credentials.json').write_text(json.dumps({'login':'test', 'password':'secret'}))
    (tmp_path/'monitoring-session.json').write_text(json.dumps('existing-token'))
    monkeypatch.setattr(m.time, 'sleep', lambda _: None)
    return tmp_path


def test_existing_token_is_reused_and_missing_data_stays_missing(configured):
    session=Mock()
    session.post.side_effect=[Response([{'vehicleId':7,'name':'Авто'}]), Response([])]
    client=m.Client(configured, session)
    vehicles=client.read('vehicles/find', {})
    rows=m.normalize(vehicles,client.read('vehicles/getlastdata', {'vehiclesIds':[7]}))
    assert rows[0]['speed'] is None and rows[0]['recordTime'] is None
    assert len(session.post.call_args_list)==2
    for call in session.post.call_args_list:
        assert call.kwargs['headers']=={'X-Auth':'existing-token'}
        assert call.kwargs['allow_redirects'] is False
        assert 'secret' not in str(call)


def test_expired_token_refreshes_once(configured):
    session=Mock()
    session.post.side_effect=[Response(None,401),Response({'AuthId':'new-token'}),Response([])]
    assert m.Client(configured,session).read('vehicles/find',{})==[]
    assert session.post.call_args_list[1].args[0]==m.BASE+'auth/login'
    assert session.post.call_args_list[1].kwargs['json']=={'login':'test','password':'secret'}
    assert json.loads((configured/'monitoring-session.json').read_text())=='new-token'
    assert (configured/'monitoring-session.json').stat().st_mode & 0o777 == 0o600


def test_bad_login_response_is_not_success_and_is_redacted(configured):
    session=Mock()
    session.post.side_effect=[Response(None,401),Response({'Error':'secret and token'})]
    with pytest.raises(ValueError,match='не выдал токен') as exc:
        m.Client(configured,session).read('vehicles/find',{})
    assert 'secret' not in str(exc.value)
    assert len(session.post.call_args_list)==2


def test_failed_sync_keeps_previous_snapshot(configured,monkeypatch):
    path=configured/'monitoring-vehicles.json';path.write_text('{"old":true}')
    session=Mock();session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    session.post.side_effect=[Response([{'vehicleId':7}]),requests.Timeout('secret')]
    monkeypatch.setattr(m.requests,'Session',lambda:session)
    with pytest.raises(ValueError,match='Предыдущая загрузка сохранена') as exc:m.sync(configured)
    assert 'secret' not in str(exc.value)
    assert path.read_text()=='{"old":true}'
    assert not m.LOCK.locked()


def test_sync_saves_only_display_fields(configured,monkeypatch):
    session=Mock();session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    session.post.side_effect=[Response([{'vehicleId':7,'name':'Авто','imei':'private'}]),
                             Response([{'vehicleId':7,'speed':0,'state':3,'latitude':50}])]
    monkeypatch.setattr(m.requests,'Session',lambda:session)
    result=m.sync(configured)
    assert result['rows'][0]['speed']==0
    assert 'imei' not in result['rows'][0] and 'latitude' not in result['rows'][0]
    assert m.snapshot(configured)==result
    assert (configured/'monitoring-vehicles.json').stat().st_mode & 0o777 == 0o600


def test_mutating_methods_and_inconsistent_ids_are_rejected(configured):
    session=Mock()
    with pytest.raises(ValueError):m.Client(configured,session).read('vehicles',{})
    assert not session.post.called
    with pytest.raises(ValueError):m.normalize([{'vehicleId':7},{'vehicleId':7}],[])
    with pytest.raises(ValueError):m.normalize([{'vehicleId':7}],[{'vehicleId':8}])


@pytest.mark.parametrize('status,kind',[(403,m.AuthenticationError),(429,m.RateLimitError)])
def test_access_and_rate_limits_are_not_retried(configured,status,kind):
    session=Mock();session.post.return_value=Response({},status)
    with pytest.raises(kind):m.Client(configured,session).read('vehicles/find',{})
    assert session.post.call_count==1
