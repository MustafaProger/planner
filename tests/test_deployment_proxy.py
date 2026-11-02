"""Public HTTPS requests through the actual Waitress proxy middleware and Flask.

Only an isolated SQLite and generated source books are used. No running service,
provider credentials, TLS certificates or nginx process is needed by these tests.
"""
from contextlib import contextmanager
from pathlib import Path

import pytest
from waitress.server import create_server
from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

from excel_fixture import books


PUBLIC = 'charterstats.ru'
LOGIN = {'name': 'Deployment test', 'password': 'test-only-deployment-password'}
FORWARDED = {'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '198.51.100.23'}


@pytest.fixture
def deployment(monkeypatch, tmp_path):
    monkeypatch.setenv('FLEET_DATA', str(tmp_path))
    monkeypatch.setenv('FLEET_PUBLIC_HOST', PUBLIC)
    monkeypatch.setenv('FLEET_TRUST_PROXY', '1')
    monkeypatch.setenv('FLEET_ALLOW_BOOTSTRAP', '0')
    monkeypatch.setenv('FLEET_SECURE_COOKIE', '1')
    from app import server
    from app.importer import load_excel
    monkeypatch.setattr(server, 'DATA', tmp_path)
    monkeypatch.setattr(server, 'DB', tmp_path / 'fleet.sqlite')
    monkeypatch.setattr(server, 'FAILURES', {})
    monkeypatch.setitem(server.app.config, 'TRUSTED_HOSTS', server.trusted_hosts())
    monkeypatch.setitem(server.app.config, 'ALLOW_BOOTSTRAP', False)
    monkeypatch.setitem(server.app.config, 'SESSION_COOKIE_SECURE', True)
    source = load_excel(*books(tmp_path / 'books'))
    monkeypatch.setattr(server, 'load_excel', lambda *args: source)
    server.init()
    with server.db() as c:
        c.execute('update users set name=?,password=? where id=1',
                  (LOGIN['name'], generate_password_hash(LOGIN['password'])))
    return server


@contextmanager
def upstream(server):
    seen = []
    def application(environ, start_response):
        seen.append({k: v for k, v in environ.items()
                     if k in ('REMOTE_ADDR', 'wsgi.url_scheme', 'HTTP_HOST')
                     or k.startswith('HTTP_X_FORWARDED') or k == 'HTTP_FORWARDED'})
        return server.app(environ, start_response)
    # Build the same middleware as serve(), without listening or starting a loop.
    transport = create_server(application, _start=False,
                              **dict(server.waitress_options(), port=0, threads=1))
    try:
        yield Client(transport.application, Response), seen
    finally:
        transport.close()
        transport.task_dispatcher.shutdown()


def request(client, path='/api/login', *, host=PUBLIC, origin=None,
            peer='127.0.0.1', headers=None, body=None, method='POST'):
    values = dict(FORWARDED, **(headers or {}))
    if origin is not None:
        values['Origin'] = origin
    return client.open(path, method=method, base_url='http://' + host,
                       headers=values, json=LOGIN if body is None else body,
                       environ_overrides={'REMOTE_ADDR': peer})


def test_https_public_login_origin_cookie_and_authenticated_session(deployment):
    with upstream(deployment) as (client, seen):
        response = request(client, origin='https://' + PUBLIC)
        assert response.status_code == 200
        cookie = response.headers['Set-Cookie']
        assert all(flag in cookie for flag in ('Secure;', 'HttpOnly;', 'SameSite=Strict'))
        assert seen[-1]['wsgi.url_scheme'] == 'https'
        assert seen[-1]['REMOTE_ADDR'] == '198.51.100.23'
        response = request(client, '/api/session', method='GET')
        assert response.json['user']['name'] == LOGIN['name']
        assert response.json['user']['role'] == 'admin'


@pytest.mark.parametrize('origin', ['https://evil.invalid', 'http://' + PUBLIC])
def test_origin_mismatch_never_sets_session(deployment, origin):
    with upstream(deployment) as (client, _):
        response = request(client, origin=origin)
        assert response.status_code == 403
        assert 'Set-Cookie' not in response.headers


@pytest.mark.parametrize('host', ['evil.invalid', 'sub.' + PUBLIC])
def test_untrusted_host_is_rejected_even_with_forwarded_public_host(deployment, host):
    with upstream(deployment) as (client, _):
        response = request(client, host=host, origin='https://' + PUBLIC,
                           headers={'X-Forwarded-Host': PUBLIC})
        assert response.status_code == 400
        assert 'Set-Cookie' not in response.headers


def test_only_loopback_peer_and_two_headers_are_trusted(deployment):
    with upstream(deployment) as (client, seen):
        response = request(client, origin='https://' + PUBLIC, headers={
            'X-Forwarded-Host': 'evil.invalid', 'X-Forwarded-Port': '8443',
            'Forwarded': 'for=127.0.0.1;proto=http;host=evil.invalid'})
        assert response.status_code == 200
        assert seen[-1]['HTTP_HOST'] == PUBLIC
        assert all(k not in seen[-1] for k in
                   ('HTTP_X_FORWARDED_HOST', 'HTTP_X_FORWARDED_PORT', 'HTTP_FORWARDED'))
        response = request(client, origin='https://' + PUBLIC, peer='203.0.113.9')
        assert response.status_code == 403
        assert seen[-1]['REMOTE_ADDR'] == '203.0.113.9'
        assert seen[-1]['wsgi.url_scheme'] == 'http'
        assert not any(k.startswith('HTTP_X_FORWARDED') for k in seen[-1])


def test_one_proxy_hop_and_login_rate_limit_use_actual_forwarded_client(deployment):
    with upstream(deployment) as (client, seen):
        response = request(client, origin='https://' + PUBLIC,
                           headers={'X-Forwarded-For': '127.0.0.1, 198.51.100.99'},
                           body=dict(LOGIN, password='wrong'))
        assert response.status_code == 401
        assert seen[-1]['REMOTE_ADDR'] == '198.51.100.99'
        assert set(deployment.FAILURES) == {'198.51.100.99'}


def test_public_bootstrap_disabled_even_with_existing_token_and_loopback(deployment):
    token_path = deployment.DATA / 'bootstrap.token'
    assert not token_path.exists()  # init() must not create a public bootstrap.
    token = 'synthetic-bootstrap-token-that-must-not-leak'
    token_path.write_text(token)
    with upstream(deployment) as (client, _):
        for forwarded_ip in ('127.0.0.1', '198.51.100.23'):
            response = request(client, '/bootstrap/' + token, method='GET',
                               headers={'X-Forwarded-For': forwarded_ip})
            assert response.status_code == 404
            assert token.encode() not in response.data
            assert 'Set-Cookie' not in response.headers
        for path in ('/data/bootstrap.token', '/data/local-login.txt', '/data/session.key'):
            response = request(client, path, method='GET')
            assert response.status_code == 404
            assert token.encode() not in response.data
    assert token_path.read_text() == token
    assert not (deployment.DATA / 'bootstrap.used').exists()


def test_bootstrap_cannot_treat_proxied_remote_user_as_loopback(deployment, monkeypatch):
    monkeypatch.setitem(deployment.app.config, 'ALLOW_BOOTSTRAP', True)
    deployment.init()
    token_path = deployment.DATA / 'bootstrap.token'
    token = token_path.read_text()
    with upstream(deployment) as (client, _):
        response = request(client, '/bootstrap/' + token, method='GET')
        assert response.status_code == 403
        assert token.encode() not in response.data
        assert token_path.exists()


def test_local_defaults_keep_login_and_one_time_bootstrap(deployment, monkeypatch):
    for name in ('FLEET_PUBLIC_HOST', 'FLEET_TRUST_PROXY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(deployment.app.config, 'TRUSTED_HOSTS', deployment.trusted_hosts())
    monkeypatch.setitem(deployment.app.config, 'ALLOW_BOOTSTRAP', True)
    monkeypatch.setitem(deployment.app.config, 'SESSION_COOKIE_SECURE', False)
    assert deployment.trusted_hosts() == ['127.0.0.1', 'localhost']
    assert 'trusted_proxy' not in deployment.waitress_options()
    deployment.init()
    token_path = deployment.DATA / 'bootstrap.token'
    token = token_path.read_text()
    with upstream(deployment) as (client, seen):
        response = request(client, host='localhost', origin='http://localhost')
        assert response.status_code == 200
        assert seen[-1]['wsgi.url_scheme'] == 'http'
        assert seen[-1]['REMOTE_ADDR'] == '127.0.0.1'
        assert 'Secure;' not in response.headers['Set-Cookie']
        response = request(client, '/bootstrap/' + token, host='localhost', method='GET')
        assert response.status_code == 302
        assert not token_path.exists()
        assert (deployment.DATA / 'bootstrap.used').exists()
        assert request(client, '/bootstrap/' + token, host='localhost', method='GET').status_code == 403


@pytest.mark.parametrize('host', ['https://charterstats.ru', 'charterstats.ru:443',
    '.charterstats.ru', '*.charterstats.ru', 'charterstats.ru/path',
    'charterstats.ru evil.invalid', 'a' * 64 + '.ru', 'user@charterstats.ru'])
def test_invalid_public_host_fails_closed_without_echo(deployment, monkeypatch, host):
    monkeypatch.setenv('FLEET_PUBLIC_HOST', host)
    with pytest.raises(ValueError) as caught:
        deployment.trusted_hosts()
    assert host not in str(caught.value)


def test_public_nginx_environment_contract():
    root = Path(__file__).resolve().parents[1]
    config = (root / 'deploy/nginx.example.conf').read_text()
    environment = (root / 'deploy/environment.example').read_text()
    for value in ('FLEET_PUBLIC_HOST=' + PUBLIC, 'FLEET_TRUST_PROXY=1',
                  'FLEET_ALLOW_BOOTSTRAP=0', 'FLEET_SECURE_COOKIE=1'):
        assert value in environment
    for value in ('server_name ' + PUBLIC + ';', 'proxy_set_header Host $host;',
                  'proxy_set_header X-Forwarded-Proto $scheme;',
                  'proxy_set_header X-Forwarded-For $remote_addr;'):
        assert value in config
    assert '$proxy_add_x_forwarded_for' not in config
    blocked = config.split('location ^~ /bootstrap/ {', 1)[1].split('}', 1)[0]
    assert 'return 404;' in blocked and 'access_log off;' in blocked
