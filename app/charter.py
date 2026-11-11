"""Local redesign API. Reads existing facts; keeps review decisions separately."""
import datetime as dt
import json
import math
import os

DEFAULTS = dict(movement_threshold=10, excess_km=30, excess_percent=10, fuel_norms={})
REVIEW_STATES = ('Не проверено', 'В работе', 'Обосновано', 'Нарушение', 'Исправлено')


def register(app, db, dataset, auth, user, audit, lock, data_dir):
    from flask import jsonify, request, session, send_file

    def state(c):
        c.execute('CREATE TABLE IF NOT EXISTS charter_state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, body TEXT NOT NULL)')
        row = c.execute('SELECT revision,body FROM charter_state WHERE id=1').fetchone()
        return dict(revision=row['revision'], **json.loads(row['body'])) if row else dict(revision=0, settings=dict(DEFAULTS), reviews={})

    @app.get('/api/charter')
    @auth()
    def charter_data():
        from app.reports import fuel_operations
        compact = request.args.get('view') == 'workspace'
        d = dataset(charter_view=True) if compact else dataset()
        account = user()
        with db() as c:
            s = state(c)
        result = dict(data=d, state=s, local_preview=os.environ.get('FLEET_LOCAL_PREVIEW') == '1')
        from app.demo_data import enabled, facts
        demo = facts(data_dir) if enabled() else None
        result['demo'] = dict(version=demo['version'], period=demo['period'], summary=demo['summary']) if demo else None
        # Match the existing role boundary for raw fuel operations and card data.
        if account['role'] == 'admin':
            result['fuel'] = demo['fuel'] if demo else fuel_operations(d, {}, data_dir)[0]
            if not demo:
                from app.rosneft_drivers import label_operations
                with db() as c:
                    label_operations(c, result['fuel'])
        else:
            result['fuel'] = []
            d['card_bindings'] = []
        if not compact:
            return jsonify(result)
        result['user'] = account
        body = app.json.dumps(result, ensure_ascii=False, sort_keys=False, separators=(',', ':'))
        response = app.response_class(body, mimetype='application/json')
        # Keep the CSRF secret outside the compressible response body.
        response.headers['X-CSRF-Token'] = session.get('csrf', '')
        return response

    @app.post('/api/charter/deviations/export')
    @auth()
    def export_deviations():
        from app.deviation_export import workbook
        # The browser sends the rows already available in the signed-in table.
        # This endpoint only formats those values; it does not query records.
        return send_file(workbook(request.get_json(silent=True)), as_attachment=True,
                         download_name='Отклонения.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @app.put('/api/charter/state')
    @auth(['admin', 'logist'])
    def charter_save():
        b = request.get_json()
        if not isinstance(b, dict):
            raise ValueError('Ожидается объект настроек или проверки.')
        u = user()
        with lock, db() as c:
            c.execute('BEGIN IMMEDIATE')
            s = state(c)
            if type(b.get('revision')) is not int or b['revision'] != s['revision']:
                return jsonify(error='Данные изменены в другой вкладке. Обновите страницу.'), 409
            if b.get('kind') == 'settings':
                if u['role'] != 'admin':
                    raise PermissionError()
                value = b.get('settings', {})
                if not isinstance(value, dict):
                    raise ValueError('Проверьте настройки.')
                settings = {}
                for key, maximum in [('movement_threshold', 1000), ('excess_km', 10000), ('excess_percent', 1000)]:
                    n = value.get(key, DEFAULTS[key])
                    if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 <= n <= maximum:
                        raise ValueError('Порог должен быть конечным неотрицательным числом.')
                    settings[key] = n
                norms = value.get('fuel_norms', {})
                if not isinstance(norms, dict) or len(norms) > 5000:
                    raise ValueError('Проверьте нормы расхода.')
                for name, n in norms.items():
                    if not isinstance(name, str) or len(name) > 200 or isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 < n <= 200:
                        raise ValueError('Норма должна быть больше нуля и не больше 200 л/100 км.')
                settings['fuel_norms'] = norms
                s['settings'] = settings
            elif b.get('kind') == 'review':
                review = b.get('review', {})
                if not isinstance(review, dict):
                    raise ValueError('Проверьте запись.')
                key = review.get('id', '')
                car = review.get('vehicle', '')
                if not isinstance(key, str) or not 1 <= len(key) <= 500:
                    raise ValueError('Не указано отклонение.')
                if u['role'] != 'admin' and car not in u['vehicles']:
                    raise PermissionError()
                status = review.get('status')
                comment = review.get('comment', '')
                if status not in REVIEW_STATES or not isinstance(comment, str) or len(comment) > 2000:
                    raise ValueError('Проверьте статус и комментарий (до 2000 символов).')
                if status in ('Обосновано', 'Нарушение', 'Исправлено') and not comment.strip():
                    raise ValueError('Добавьте обоснование решения.')
                old = s['reviews'].get(key, {})
                event = dict(status=status, comment=comment, author=u['name'], at=dt.datetime.now(dt.timezone.utc).isoformat())
                s['reviews'][key] = dict(event, vehicle=car, history=[*old.get('history', []), event])
            else:
                raise ValueError('Неизвестное действие.')
            revision = s.pop('revision') + 1
            c.execute('INSERT INTO charter_state VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,body=excluded.body', (revision, json.dumps(s, ensure_ascii=False)))
            audit(c, 'charter ' + b['kind'], json.dumps(b, ensure_ascii=False))
        return jsonify(revision=revision, **s)
