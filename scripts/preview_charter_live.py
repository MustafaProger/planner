"""Serve the local frontend with read-only requests to the production API."""
import re
import secrets
import subprocess
import sys
from pathlib import Path
from time import monotonic

import requests
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory
from waitress import serve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.charter import CHARTER_PAGES

BUILD = ROOT / '.local' / 'charter-live-ui'
UPSTREAM = 'https://charterstats.ru'
COOKIE = 'charter_live_preview'
SESSION_AGE = 12 * 60 * 60
READ_PATHS = {'charter', 'users', 'users/permissions', 'audit', 'connections', 'rosneft/driver-assignments', 'tariffs/quote'}
app = Flask(__name__, static_folder=None, template_folder=str(ROOT / 'app/templates'))
app.config.update(TRUSTED_HOSTS=['127.0.0.1', 'localhost'], MAX_CONTENT_LENGTH=16 * 1024)
sessions = {}


def session_token():
    return request.cookies.get(COOKIE, '')


def upstream_session():
    session = sessions.get(session_token())
    if session and monotonic() < session[0]:
        return session[1]


@app.after_request
def headers(response):
    response.headers.setdefault('Cache-Control', 'no-store')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


@app.before_request
def check_origin():
    if request.method == 'POST' and request.headers.get('Origin') not in (None, request.host_url.rstrip('/')):
        abort(403)


@app.get('/static/charter/<path:filename>')
def asset(filename):
    return send_from_directory(BUILD, filename, max_age=31536000 if filename.startswith('assets/') else 0)


@app.route('/', methods=['GET', 'POST'])
def index():
    return workspace('overview')


@app.route('/<page>', methods=['GET', 'POST'])
def workspace(page):
    if page not in CHARTER_PAGES:
        abort(404)
    if request.method in ('GET', 'HEAD'):
        if upstream_session():
            if request.path == '/':
                return redirect('/overview')
            return send_from_directory(BUILD, 'index.html')
        return render_template('charter_login.html')

    try:
        with requests.post(
            UPSTREAM + '/api/login',
            json={key: request.form.get(key, '') for key in ('name', 'password')},
            timeout=(5, 30),
            allow_redirects=False,
        ) as upstream:
            if upstream.status_code in (400, 401, 429):
                return render_template('charter_login.html', error=upstream.json()['error']), upstream.status_code
            upstream_cookies = upstream.cookies.get_dict()
            if upstream.status_code != 200 or not upstream_cookies:
                raise ValueError('Missing session')
    except (requests.RequestException, ValueError, KeyError):
        return render_template('charter_login.html', error='Рабочий API входа недоступен.'), 502

    sessions.pop(session_token(), None)
    now = monotonic()
    for expired, (until, _) in tuple(sessions.items()):
        if until <= now:
            sessions.pop(expired, None)
    token = secrets.token_urlsafe(32)
    sessions[token] = (now + SESSION_AGE, upstream_cookies)
    response = redirect('/' + page, code=303)
    response.set_cookie(COOKIE, token, max_age=SESSION_AGE, httponly=True, samesite='Strict')
    return response


@app.get('/charter', strict_slashes=False)
def old_index():
    return old_workspace('overview')


@app.get('/charter/<page>')
def old_workspace(page):
    if page not in CHARTER_PAGES:
        abort(404)
    query = request.query_string.decode('latin-1')
    return redirect('/' + page + ('?' + query if query else ''))


@app.post('/api/logout')
def logout():
    sessions.pop(session_token(), None)
    response = jsonify(ok=True)
    response.delete_cookie(COOKIE)
    return response


@app.route('/api/<path:path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
def api(path):
    if request.method not in ('GET', 'HEAD'):
        return jsonify(error='Локальный просмотр рабочего API доступен только для чтения.'), 403
    if path not in READ_PATHS and not re.fullmatch(r'audit/[0-9]+', path):
        abort(404)
    cookies = upstream_session()
    if not cookies:
        return jsonify(error='Войдите в приложение.'), 401
    try:
        upstream = requests.request(
            request.method, UPSTREAM + '/api/' + path,
            params=list(request.args.items(multi=True)),
            headers={'Accept-Encoding': request.headers.get('Accept-Encoding', 'identity')},
            cookies=cookies, stream=True, allow_redirects=False, timeout=(5, 60),
        )
    except requests.RequestException:
        return jsonify(error='Рабочий API недоступен.'), 502

    if upstream.status_code == 401:
        upstream.close()
        return expired_session()
    if upstream.is_redirect or 'application/json' not in upstream.headers.get('Content-Type', ''):
        upstream.close()
        return jsonify(error='Рабочий API вернул неожиданный ответ.'), 502

    response = Response(upstream.raw.stream(64 * 1024, decode_content=False), status=upstream.status_code)
    response.call_on_close(upstream.close)
    for header in ('Content-Type', 'Content-Encoding', 'Content-Length'):
        if header in upstream.headers:
            response.headers[header] = upstream.headers[header]
    return response


def expired_session():
    sessions.pop(session_token(), None)
    response = jsonify(error='Войдите в приложение.')
    response.status_code = 401
    response.delete_cookie(COOKIE)
    return response


if __name__ == '__main__':
    subprocess.run(
        ['npm', 'run', 'build', '--prefix', 'frontend', '--', '--mode', 'live-preview', '--outDir', str(BUILD)],
        cwd=ROOT, check=True,
    )
    print('CharterStats live preview: http://127.0.0.1:8777/overview', flush=True)
    serve(app, host='127.0.0.1', port=8777, threads=6)
