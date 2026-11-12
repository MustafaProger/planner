"""Authorization, persistence and concurrent edits for the new local UI API."""
import json
import sqlite3
import threading
import functools
from contextlib import contextmanager
import pytest
from flask import Flask, request, jsonify
from app.charter import register
from app.workspace import schema

@pytest.fixture
def client(tmp_path):
    app=Flask(__name__);app.testing=True
    role={'role':'admin','name':'Тест','vehicles':['А001АА77']}
    @contextmanager
    def db():
        with sqlite3.connect(tmp_path/'test.sqlite') as c:
            c.row_factory=sqlite3.Row
            yield c
    def auth(roles=None):
        def decorate(fn):
            @functools.wraps(fn)
            def wrapped(*a,**kw):
                if roles and role['role'] not in roles:return jsonify(error='role'),403
                if request.method=='PUT' and request.headers.get('X-CSRF-Token')!='test':return jsonify(error='csrf'),403
                return fn(*a,**kw)
            return wrapped
        return decorate
    @app.errorhandler(ValueError)
    def invalid(e):return jsonify(error=str(e)),400
    @app.errorhandler(PermissionError)
    def forbidden(e):return jsonify(error='forbidden'),403
    with db() as c:
        schema(c)
    d=dict(directories={'vehicles':[]},trips=[],plans=[],satellite=[],statuses=[],card_bindings=[],expenses=[])
    register(app,db,lambda:d,auth,lambda:role,lambda *a:None,threading.Lock(),tmp_path)
    return app.test_client(),role,db

H={'X-CSRF-Token':'test'}
def test_state_roles_csrf_validation_and_conflicts(client):
    c,role,db=client
    assert c.get('/api/charter').json['state']['revision']==0
    body={'kind':'settings','revision':0,'settings':{'movement_threshold':10,'excess_km':30,'excess_percent':10,'fuel_norms':{}}}
    assert c.put('/api/charter/state',json=body).status_code==403
    role['role']='viewer'
    assert c.put('/api/charter/state',json=body,headers=H).status_code==403
    role['role']='logist'
    assert c.put('/api/charter/state',json=body,headers=H).status_code==403
    role['role']='admin'
    assert c.put('/api/charter/state',json={**body,'settings':{'movement_threshold':-1}},headers=H).status_code==400
    assert c.put('/api/charter/state',json=body,headers=H).json['revision']==1
    assert c.put('/api/charter/state',json=body,headers=H).status_code==409
    assert c.get('/api/charter').json['state']['settings']['movement_threshold']==10

def test_review_history_and_assigned_vehicle(client):
    c,role,db=client
    role['role']='logist'
    ident = 'Не заполнено|А001АА77|2026-11-12'
    b={'kind':'review','revision':0,'review':{'id':ident,'vehicle':'А002АА77','status':'В работе','comment':''}}
    assert c.put('/api/charter/state',json=b,headers=H).status_code==403
    b['review']['vehicle']='А001АА77'
    forged = {**b, 'review': {**b['review'], 'id': ident.replace('А001АА77', 'А002АА77')}}
    assert c.put('/api/charter/state', json=forged, headers=H).status_code==403
    assert c.put('/api/charter/state',json=b,headers=H).json['revision']==1
    b.update(revision=1);b['review']['status']='Обосновано'
    assert c.put('/api/charter/state',json=b,headers=H).status_code==400
    b['review']['comment']='Перегон на сервис'
    assert c.put('/api/charter/state',json=b,headers=H).status_code==200
    state=c.get('/api/charter').json['state']
    assert len(state['reviews'][ident]['history'])==2
    assert state['reviews'][ident]['history'][0]['status']=='В работе'
    assert state['reviews'][ident]['history'][1]['author']=='Тест'

def test_explicit_catalog_links_survive_legacy_form_and_reject_unknown_targets():
    from app import workspace as w
    c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;w.schema(c)
    carrier=w.save_catalog(c,'carriers',{'name':'Чартер'})
    category=w.save_catalog(c,'transport_types',{'name':'1,5 тонны'})
    ident=w.save_catalog(c,'vehicles',{'name':'А123АА777','carrier_id':carrier,'transport_type_id':category})
    row=w.catalogs(c)['vehicles'][0]
    assert row['carrier_id']==carrier
    w.save_catalog(c,'vehicles',{'name':row['name'],'revision':row['revision']},ident)
    row=w.catalogs(c)['vehicles'][0]
    assert row['carrier_id']==carrier and row['transport_type_id']==category
    with pytest.raises(ValueError):w.save_catalog(c,'vehicles',{**row,'carrier_id':'missing'},ident)
    w.save_catalog(c,'vehicles',{**row,'carrier_id':''},ident)
    assert w.catalogs(c)['vehicles'][0]['carrier_id']==''
