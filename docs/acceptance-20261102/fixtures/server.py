"""Disposable customer-acceptance host. Never opens the project's data directory."""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

with tempfile.TemporaryDirectory(prefix='fleet-customer-acceptance-') as folder:
    os.environ['FLEET_DATA'] = folder
    os.environ['FLEET_SCHEDULER'] = 'disabled'
    os.environ['FLEET_ALLOW_BOOTSTRAP'] = '0'
    os.environ.pop('FLEET_SECURE_COOKIE', None)
    os.environ.pop('FLEET_PUBLIC_HOST', None)
    from excel_fixture import books
    from app.importer import load_excel
    from app import server
    from flask import request, abort
    from werkzeug.security import generate_password_hash
    from werkzeug.serving import make_server

    paths = books(Path(folder) / 'synthetic-books')
    seed = load_excel(*paths)
    seed['trips'][0]['km'] = None
    server.load_excel = lambda *args: seed
    server.resolve_sources = lambda **kwargs: paths
    server.init()
    with server.db() as c:
        c.execute('delete from users')
        for role in ('admin', 'logist', 'viewer'):
            c.execute('insert into users(name,password,role,vehicles) values(?,?,?,?)',
                      ('acceptance-' + role, generate_password_hash('isolated-test-only-password'), role,
                       json.dumps(['Т711РМ797'] if role == 'logist' else [])))
    @server.app.before_request
    def no_provider_mutations():
        if request.method != 'GET' and (request.path in ('/api/refresh', '/api/import', '/api/connections/check')
                or request.path.endswith(('/sync', '/authorize', '/reconcile'))):
            abort(403)
    host = make_server('127.0.0.1', 0, server.app, threaded=True)
    def finish(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    print(json.dumps({'port': host.server_port, 'synthetic': True, 'scheduler': 'disabled'}), flush=True)
    try:
        host.serve_forever()
    finally:
        host.server_close()
