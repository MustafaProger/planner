"""Authenticated routes for provenance-backed mileage and actual intervals."""
from flask import Blueprint, jsonify, request, session
from app import activity, mileage, shifts, workspace as ws

def register(app,db,dataset,auth,audit,lock):
    bp=Blueprint('evidence',__name__)
    @bp.errorhandler(mileage.Conflict)
    def conflict(e):return jsonify(error=str(e)),409

    @bp.get('/api/evidence')
    @auth()
    def read():
        data=dataset()
        with db() as c:
            intervals=shifts.rows(c)
            observations=[]
        start=request.args.get('from','');end=request.args.get('to','9999-12-31')
        measurements=[m for m in shifts.daily_measurements(data) if start<=m['date']<=end]
        return jsonify(shifts=intervals,mileage=observations,allocation=shifts.allocate(intervals,measurements),automatic_mileage=False)

    def shift_snapshot(c, ident):
        row = activity.row_body(c, 'actual_shifts', ident)
        if row is None:
            return None
        cats = ws.catalogs(c)
        return {**row, **{key: (ws.lookup(cats, key+'s', row[key+'_id']) or {}).get('name')
                          for key in ('vehicle', 'driver')}}

    @bp.post('/api/evidence/shifts')
    @bp.put('/api/evidence/shifts/<ident>')
    @auth(['admin'])
    def save_shift(ident=None):
        with lock,db() as c:
            c.execute('BEGIN IMMEDIATE')
            before = shift_snapshot(c, ident)
            result=shifts.save(c,request.get_json(),session.get('uid'),ident)
            after = shift_snapshot(c, result['id'])
            audit(c, 'actual_shift', after['vehicle'] or result['id'], activity.changes(
                before, after, fields=('vehicle', 'driver', 'start', 'end', 'hours', 'source_ref')))
        return jsonify(result)

    @bp.delete('/api/evidence/shifts/<ident>')
    @auth(['admin'])
    def delete_shift(ident):
        b=request.get_json(silent=True) or {}
        with lock,db() as c:
            c.execute('BEGIN IMMEDIATE')
            before = shift_snapshot(c, ident)
            shifts.delete(c,ident,b.get('revision'),session.get('uid'))
            audit(c, 'delete_actual_shift', before['vehicle'] or ident, activity.changes(
                before, None, fields=('vehicle', 'driver', 'start', 'end', 'hours', 'source_ref')))
        return jsonify(ok=True)
    app.register_blueprint(bp)
