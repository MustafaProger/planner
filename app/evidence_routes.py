"""Authenticated routes for provenance-backed mileage and actual intervals."""
from flask import Blueprint, jsonify, request, session
from app import mileage, shifts

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

    @bp.post('/api/evidence/shifts')
    @bp.put('/api/evidence/shifts/<ident>')
    @auth(['admin'])
    def save_shift(ident=None):
        with lock,db() as c:
            c.execute('BEGIN IMMEDIATE')
            result=shifts.save(c,request.get_json(),session.get('uid'),ident)
            audit(c,'actual_shift',result['id'])
        return jsonify(result)

    @bp.delete('/api/evidence/shifts/<ident>')
    @auth(['admin'])
    def delete_shift(ident):
        b=request.get_json(silent=True) or {}
        with lock,db() as c:
            c.execute('BEGIN IMMEDIATE')
            shifts.delete(c,ident,b.get('revision'),session.get('uid'));audit(c,'delete_actual_shift',ident)
        return jsonify(ok=True)
    app.register_blueprint(bp)
