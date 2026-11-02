"""Disposable host for report drill-down acceptance. No real data or credentials."""
import copy
import json
import os
from pathlib import Path
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

with tempfile.TemporaryDirectory(prefix='fleet-functional-acceptance-') as folder:
    os.environ.update(FLEET_DATA=folder, FLEET_SCHEDULER='disabled', FLEET_ALLOW_BOOTSTRAP='0')
    os.environ.pop('FLEET_SECURE_COOKIE', None)
    os.environ.pop('FLEET_PUBLIC_HOST', None)
    from excel_fixture import books
    from app.importer import load_excel
    from app import server, workspace as ws
    from flask import request, abort
    from werkzeug.security import generate_password_hash
    from werkzeug.serving import make_server

    paths = books(Path(folder) / 'synthetic-books')
    seed = load_excel(*paths)
    first_driver = 'Водитель · Первый'
    second_driver = 'Водитель Второй'
    first_car, second_car = 'Т711РМ797', 'У930ЕХ797'
    seed['vehicles']['А111АА797'] = 'Synthetic satellite-only vehicle'
    seed['drivers'] = {first_driver: 'Компания А', second_driver: 'Компания Б'}
    for row in seed['trips']:
        row['driver'] = first_driver
    seed['trips'][0]['km'] = None
    template = copy.deepcopy(seed['trips'][0])
    for ident, day, car, driver, revenue, payout, km, duration in [
        ('5', '2026-08-02', second_car, first_driver, 500, 200, 50, 2),
        ('6', '2026-08-01', first_car, second_driver, 700, 300, 70, 3),
        ('7', '2026-09-01', second_car, first_driver, 900, 350, 90, 1),
    ]:
        seed['trips'].append(dict(template, id=ident, date=day, start=day+'T08:00:00',
                                 end=day+f'T{8+duration:02}:00:00', vehicle=car, driver=driver,
                                 revenue=revenue, payout=payout, km=km, hours=duration,
                                 source='Synthetic trip '+ident))
    seed['plans'] = []
    seed['statuses'] = []
    satellite = copy.deepcopy(seed['satellite'][0])
    seed['satellite'].append(dict(satellite, date='2026-08-02', vehicle=second_car,
        start='2026-08-02T00:00:00', end='2026-08-03T00:00:00', km=150,
        source='Synthetic satellite other vehicle'))
    seed['satellite'].append(dict(satellite, date='2026-08-03', vehicle=first_car,
        start='2026-08-03T00:00:00', end='2026-08-04T00:00:00', km=999,
        source='Synthetic satellite outside selected day'))
    seed['satellite'].append(dict(satellite, date='2026-08-04', vehicle='А111АА797',
        start='2026-08-04T00:00:00', end='2026-08-05T00:00:00', km=88,
        source='Synthetic satellite-only vehicle'))
    server.load_excel = lambda *args: seed
    server.resolve_sources = lambda **kwargs: paths
    server.init()
    # Saved fake provider response: API overrides mileage, Excel interval remains available.
    (Path(folder)/'monitoring-vehicles.json').write_text(json.dumps({'rows':[{'vehicleId':1,'name':first_car}]}))
    (Path(folder)/'monitoring-history.json').write_text(json.dumps({'cells':{'1:2026-08-01':{
        'vehicleId':1,'date':'2026-08-01',
        'mileage':{'km':334,'engine_hours':5,'status':'ok','synced_at':'2026-08-02T06:00:00+00:00'},
        'fuel':{'fuel_liters':25,'status':'ok','synced_at':'2026-08-02T06:00:00+00:00'}
    }}}))
    with server.db() as c:
        c.execute('delete from users')
        for role in ('admin', 'viewer'):
            c.execute('insert into users(name,password,role,vehicles) values(?,?,?,?)',
                      ('acceptance-'+role, generate_password_hash('isolated-test-only-password'), role, '[]'))
        admin = dict(id=1, role='admin', vehicles=[])
        route = ws.catalogs(c)['routes'][0]['id']
        for day, car, driver, slot, state in [
            ('2026-08-01', first_car, first_driver, 'first', 'scheduled'),
            ('2026-08-01', first_car, first_driver, 'second', 'scheduled'),
            ('2026-08-02', second_car, first_driver, 'first', 'scheduled'),
            ('2026-08-01', first_car, second_driver, 'first', 'scheduled'),
            ('2026-08-01', first_car, first_driver, 'excluded-review', 'review'),
            ('2026-08-01', first_car, first_driver, 'excluded-cancelled', 'cancelled'),
            ('2026-09-01', second_car, first_driver, 'outside-month', 'scheduled'),
        ]:
            ws.create_records(c, 'plans', dict(date=day, vehicle=car, driver=driver,
                              route_id=route, slot=slot, state=state), admin)
        ws.create_records(c, 'statuses', dict(date='2026-08-01',kind='vehicle',entity=first_car,reason='Сервис'),admin)
    @server.app.before_request
    def no_provider_mutations():
        if request.method != 'GET' and (request.path in ('/api/refresh', '/api/import', '/api/connections/check')
                or request.path.endswith(('/sync', '/authorize', '/reconcile'))):
            abort(403)
    host = make_server('127.0.0.1', 0, server.app, threaded=True)
    def finish(*_): raise SystemExit(0)
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    print(json.dumps({'port':host.server_port,'synthetic':True,'scheduler':'disabled'},ensure_ascii=False),flush=True)
    try: host.serve_forever()
    finally: host.server_close()
