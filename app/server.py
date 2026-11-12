import datetime as dt, functools, hashlib, io, json, os, re, secrets, sqlite3, threading, zipfile
from pathlib import Path
from flask import Flask,request,jsonify,session,send_from_directory,redirect,abort,g,make_response,render_template
from flask.sessions import SecureCookieSessionInterface
from werkzeug.security import generate_password_hash,check_password_hash
from app.normalization import vehicle
from app.analytics import report,reconcile
from app import workspace as ws
from app.charter import CHARTER_PAGES
ROOT=Path(__file__).resolve().parent.parent
DATA=Path(os.environ.get('FLEET_DATA',ROOT/'data'));DATA.mkdir(exist_ok=True,parents=True);os.chmod(DATA,0o700)
DB=DATA/'fleet.sqlite'
def trusted_hosts():
    hosts=['127.0.0.1','localhost']
    public=os.environ.get('FLEET_PUBLIC_HOST','').strip().lower()
    if public:
        # A single exact DNS host, never a URL, port, wildcard or subdomain rule.
        if len(public)>253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*',public):
            raise ValueError('FLEET_PUBLIC_HOST must be a single DNS hostname')
        hosts.append(public)
    return hosts

def waitress_options():
    options=dict(host='127.0.0.1',port=int(os.environ.get('PORT',8765)),threads=6)
    if os.environ.get('FLEET_TRUST_PROXY')=='1':
        options.update(trusted_proxy='127.0.0.1',trusted_proxy_count=1,
                       trusted_proxy_headers={'x-forwarded-for','x-forwarded-proto'},
                       clear_untrusted_proxy_headers=True)
    return options

app=Flask(__name__,static_folder='static');app.config.update(MAX_CONTENT_LENGTH=25*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=12),TRUSTED_HOSTS=trusted_hosts())

class FleetSessionInterface(SecureCookieSessionInterface):
    def save_session(self, app, session, response):
        if request.endpoint != 'static':
            super().save_session(app, session, response)

app.session_interface=FleetSessionInterface()
app.config['SESSION_COOKIE_SECURE']=os.environ.get('FLEET_SECURE_COOKIE')=='1'
app.config['ALLOW_BOOTSTRAP']=os.environ.get('FLEET_ALLOW_BOOTSTRAP','1')=='1'
key=DATA/'session.key'
if not key.exists():key.write_text(secrets.token_hex(32));os.chmod(key,0o600)
app.secret_key=key.read_text()
app.config['SESSION_COOKIE_NAME']='fleet_'+hashlib.sha256(str(DATA).encode()).hexdigest()[:10]
LOCK=threading.Lock()
def db():
    c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row;return c
def init():
    with db() as c:
        c.executescript('CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT); CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT UNIQUE,password TEXT,role TEXT,vehicles TEXT); CREATE TABLE IF NOT EXISTS manual(id TEXT PRIMARY KEY,kind TEXT,body TEXT,created_by INTEGER,deleted INTEGER DEFAULT 0); CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT,user_id INTEGER,action TEXT,detail TEXT);')
        initial_source=None
        if not c.execute('select 1 from snapshot').fetchone():
            # API-only installations start with an empty workspace.
            initial_source=dict(trips=[],satellite=[],statuses=[],plans=[],routes=[],vehicles={},drivers={},meta=dict(files=[],issues=[],source='API',counts={}))
        if not c.execute('select 1 from users').fetchone():
            pwd=secrets.token_urlsafe(18);c.execute('insert into users(name,password,role,vehicles) values(?,?,?,?)',('Руководитель',generate_password_hash(pwd),'admin','[]'))
            (DATA/'local-login.txt').write_text('Пользователь: Руководитель\nПароль: '+pwd+'\n');os.chmod(DATA/'local-login.txt',0o600)
        if not c.execute('select 1 from snapshot').fetchone():c.execute('insert into snapshot values(1,?)',(json.dumps(initial_source,ensure_ascii=False),))
    with db() as c:
        # Snapshot backup before the first non-destructive workspace migration.
        has_workspace=c.execute("select 1 from sqlite_master where name='workspace_meta'").fetchone()
        if not has_workspace:
            backup=DATA/'before-workspace-v2.sqlite'
            if not backup.exists():
                with sqlite3.connect(backup) as target:c.backup(target)
                os.chmod(backup,0o600)
        if has_workspace and c.execute("select 1 from workspace_meta where key='initialized'").fetchone():
            ws.schema(c)
        else:
            original=json.loads(c.execute('select body from snapshot where id=1').fetchone()[0])
            ws.initialize(c,original,c.execute('select * from manual').fetchall())
    os.chmod(DB,0o600)
    if app.config['ALLOW_BOOTSTRAP'] and not (DATA/'bootstrap.used').exists() and not (DATA/'bootstrap.token').exists():(DATA/'bootstrap.token').write_text(secrets.token_urlsafe(32));os.chmod(DATA/'bootstrap.token',0o600)
def audit(c,action,detail):c.execute('insert into audit(at,user_id,action,detail) values(?,?,?,?)',(dt.datetime.now(dt.timezone.utc).isoformat(),session.get('uid'),action,detail))
def user():
    uid=session.get('uid')
    if uid is None:return None
    if getattr(g,'fleet_user',None) and g.fleet_user['id']==uid:return g.fleet_user
    with db() as c:
        r=c.execute('select id,name,role,vehicles from users where id=?',(uid,)).fetchone()
        if not r:return None
        u=dict(r)
        vehicles=json.loads(u['vehicles'])
        if vehicles:
            cats=ws.catalogs(c)
            vehicles=[(ws.lookup(cats,'vehicles',v) or {'name':v})['name'] for v in vehicles]
    u['vehicles']=vehicles
    g.fleet_user=u
    return u
def auth(roles=None):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args,**kwargs):
            u=user()
            if not u:return jsonify(error='Войдите в приложение'),401
            if roles and u['role'] not in roles:return jsonify(error='Недостаточно прав'),403
            if request.method not in ('GET','HEAD') and request.headers.get('X-CSRF-Token')!=session.get('csrf'):return jsonify(error='Обновите страницу: проверка сессии'),403
            return fn(*args,**kwargs)
        return wrapped
    return decorator
def dataset(*, charter_view=False):
    with db() as c:d=ws.dataset(c,charter_view=charter_view)
    from app.demo_data import enabled, facts
    if enabled():
        fixture=facts(DATA)
        d['satellite']=fixture['satellite']
        d['satellite_raw']=[]
        d['meta'].update(demo=True,source=fixture['source'],imported_at=fixture['created_at'])
        return d
    from app.monitoring_history import daily_rows,merge_satellite
    names={name for r in d['directories']['vehicles'] for name in [r['name'],*r.get('aliases',[])]}
    history=daily_rows(DATA,names)
    indexes=ws.catalog_indexes(d['directories'])
    for row in history:ws.resolve_row(row,d['directories'],indexes=indexes)
    d['satellite_raw']=[]
    d['satellite']=merge_satellite([],history)
    d['meta']['monitoring_history_days']=len(history)
    return d

@app.errorhandler(PermissionError)
def forbidden(e):return jsonify(error='Недостаточно прав для этой записи'),403

@app.get('/api/workspace/report')
@auth()
def workspace_report():
    from app.reports import build
    result=build(dataset(),request.args,DATA)
    if user()['role']!='admin':result.pop('operations',None)
    return jsonify(result)

@app.get('/api/workspace/report/details')
@auth()
def workspace_report_details():
    from app.reports import report_details
    result=report_details(dataset(),request.args)
    if result is None:return jsonify(error='Строка отчета больше не найдена. Перечитайте отчет.'),404
    return jsonify(result)

@app.post('/api/catalog/<kind>')
@app.put('/api/catalog/<kind>/<ident>')
@auth(['admin'])
def catalog_save(kind,ident=None):
    with LOCK,db() as c:
        result=ws.save_catalog(c,kind,request.get_json(),ident)
        audit(c,'catalog '+kind,result)
    return jsonify(id=result)

@app.post('/api/catalog/<kind>/merge')
@auth(['admin'])
def catalog_merge(kind):
    b=request.get_json();ws.body(b)
    with LOCK,db() as c:
        ws.merge_catalog(c,kind,b.get('source'),b.get('target'));audit(c,'merge '+kind,str(b.get('source'))+' → '+str(b.get('target')))
    return jsonify(ok=True)

@app.post('/api/tariffs')
@auth(['admin'])
def tariff_save():
    with LOCK,db() as c:
        result=ws.save_tariff(c,request.get_json());audit(c,'tariff',result)
    return jsonify(id=result)

@app.get('/api/tariffs/quote')
@auth()
def tariff_quote():
    with db() as c:
        route=ws.lookup(ws.catalogs(c),'routes',request.args.get('route'),True)
        if not route:raise ValueError('Маршрут не найден.')
        return jsonify(ws.current_rate(c,route['id'],ws.iso(request.args.get('date'))))

@app.put('/api/records/<ident>')
@auth(['admin','logist'])
def record_save(ident):
    with LOCK,db() as c:
        ws.edit_record(c,ident,request.get_json(),user());audit(c,'edit record',ident)
    return jsonify(ok=True)

@app.post('/api/workspace/<kind>')
@app.put('/api/workspace/<kind>/<ident>')
@auth(['admin'])
def extra_save(kind,ident=None):
    with LOCK,db() as c:
        result=ws.save_extra(c,kind,request.get_json(),user(),ident);audit(c,kind,result)
    return jsonify(id=result)

@app.get('/api/workspace/coverage/preview')
@auth(['admin'])
def coverage_preview():
    from app.coverage import preview
    start=ws.iso(request.args.get('start'));end=ws.iso(request.args.get('end'))
    if start>end:raise ValueError('Конец периода раньше начала.')
    with db() as c:return jsonify(preview(ws.dataset(c),request.args.get('source'),start,end))

@app.delete('/api/workspace/<kind>/<ident>')
@auth(['admin'])
def extra_delete(kind,ident):
    if kind not in ('coverage','card_bindings','expenses'):abort(404)
    with LOCK,db() as c:
        ws.delete_extra(c,kind,ident,request.get_json(silent=True) or {},user())
        audit(c,'remove '+kind,ident)
    return jsonify(ok=True)

@app.after_request
def headers(r):
    path=request.path
    immutable = r.status_code in (200, 206, 304) and re.fullmatch(r'/static/charter/assets/[\w-]+-[\w-]{8}\.(?:js|css)',path,re.ASCII)
    cache='public, max-age=31536000, immutable' if immutable else 'no-store'
    r.headers.update({'Cache-Control':cache,'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'"})
    r.headers.setdefault('Referrer-Policy','no-referrer')
    return r
@app.errorhandler(ws.ConflictError)
def conflict(e):return jsonify(error=str(e),conflict=True),409
@app.errorhandler(ValueError)
def bad(e):return jsonify(error=str(e)),400
@app.errorhandler(413)
def large(e):return jsonify(error='Файл больше 25 МБ'),413
def charter_login_form(error=None,status=200):
    response=make_response(render_template('charter_login.html',error=error),status)
    response.headers['Referrer-Policy']='same-origin'
    return response

@app.route('/<page>',methods=['GET','POST'])
def charter_page(page):
    if page not in CHARTER_PAGES:abort(404)
    if request.method=='POST':
        error,status=authenticate(request.form)
        if error:return charter_login_form(error,status)
        return redirect('/'+page,code=303)
    if not user():return charter_login_form()
    return send_from_directory(app.static_folder,'charter/index.html')

@app.route('/',methods=['GET','POST'])
def index():
    if request.method!='POST' and user():return redirect('/overview')
    return charter_page('overview')

@app.get('/charter',strict_slashes=False)
def old_charter_root():return old_charter_page('overview')

def old_charter_page(page):
    if page not in CHARTER_PAGES:abort(404)
    query=request.query_string.decode('latin-1')
    return redirect('/'+page+('?' + query if query else ''),code=302)

@app.post('/charter/<page>')
def charter_login(page):return charter_page(page)

@app.get('/<section>/<page>')
def page(section,page):
    if section=='charter':return old_charter_page(page)
    if section=='integrations' and page=='axenta':return redirect('/integrations/monitoring',code=302)
    # Old bookmarks now enter the matching area of the unified CharterStats shell.
    legacy={
        ('analytics','dashboard'):'overview',('analytics','statistics'):'overview',
        ('analytics','comparison'):'compare',('analytics','reconcile'):'compare',
        ('analytics','planreport'):'planner',('analytics','downtime'):'calendar',
        ('analytics','economics'):'routes',('planning','calendar'):'calendar',
        ('planning','planner'):'planner',('data','orders'):'data',
        ('data','monitoringdata'):'data',('data','neftmdata'):'data',
        ('data','rosneftdata'):'data',('data','coverage'):'data',
        ('data','fuelcards'):'data',('data','expenses'):'data',
        ('data','directories'):'directories',('data','connections'):'connections',
        ('data','users'):'users',('data','quality'):'control',
        ('integrations','neftm'):'connections',('integrations','monitoring'):'connections',
        ('integrations','rosneft'):'connections',('integrations','transtrade'):'connections',
        ('control','quality'):'control',('control','coverage'):'data',
        ('control','fuelcards'):'data',('control','expenses'):'data',
        ('control','evidence'):'data',('settings','connections'):'connections',
        ('settings','users'):'users',('help','guide'):'settings',
    }
    if (section,page) in legacy:return old_charter_page(legacy[(section,page)])
    abort(404)
@app.get('/bootstrap/<token>')
def bootstrap(token):
    if not app.config['ALLOW_BOOTSTRAP']:abort(404)
    p=DATA/'bootstrap.token'
    if request.remote_addr!='127.0.0.1' or not p.exists() or not secrets.compare_digest(token,p.read_text()):abort(403)
    session.clear();session.update(uid=1,csrf=secrets.token_hex(24));session.permanent=True;p.unlink();(DATA/'bootstrap.used').touch(mode=0o600);return redirect('/')
FAILURES={}
@app.post('/api/login')
def login():
    error,status=authenticate(request.get_json())
    if error:return jsonify(error=error),status
    return jsonify(ok=True)

def authenticate(b):
    if request.headers.get('Origin') not in (None,request.host_url.rstrip('/')):abort(403)
    now=dt.datetime.now().timestamp();ip=request.remote_addr;history=[x for x in FAILURES.get(ip,[]) if now-x<300]
    if len(history)>=10:return 'Слишком много попыток. Повторите через 5 минут',429
    if not hasattr(b,'get') or not isinstance(b.get('name'),str):return 'Укажите логин и пароль',400
    with db() as c:u=c.execute('select * from users where name=?',(b.get('name'),)).fetchone()
    if not u or not check_password_hash(u['password'],str(b.get('password',''))):FAILURES[ip]=history+[now];return 'Неверный логин или пароль',401
    session.clear();session.update(uid=u['id'],csrf=secrets.token_hex(24));session.permanent=True
    return None,200
@app.post('/api/logout')
@auth()
def logout():session.clear();return jsonify(ok=True)
@app.get('/api/session')
def who():return jsonify(user=user(),csrf=session.get('csrf'))
@app.get('/api/data')
@auth()
def data():
    d=dataset()
    if user()['role']!='admin':d['card_bindings']=[]
    return jsonify(d)
@app.get('/api/report')
@auth()
def get_report():return jsonify(report(dataset(),request.args))
@app.get('/api/reconcile')
@auth()
def get_reconcile():return jsonify(reconcile(dataset(),request.args))
@app.get('/api/reconcile/details')
@auth()
def get_reconcile_details():
    from app.reports import reconcile_details
    result=reconcile_details(dataset(),request.args)
    if result is None:return jsonify(error='За выбранный день нет данных сверки.'),404
    return jsonify(result)
def validate_day(v):return dt.date.fromisoformat(v).isoformat()
def allowed_car(u,car):return u['role']=='admin' or car in u['vehicles']
@app.post('/api/manual/<kind>')
@auth(['admin','logist'])
def create_manual(kind):
    if kind not in ('statuses','plans','trips'):abort(404)
    with LOCK,db() as c:
        created=ws.create_records(c,kind,request.get_json(),user());audit(c,'create '+kind,str(created))
    return jsonify(created=created)

@app.put('/api/manual/statuses')
@auth(['admin','logist'])
def replace_manual_statuses():
    with LOCK,db() as c:
        changed=ws.replace_statuses(c,request.get_json(),user())
        if changed:audit(c,'replace statuses',str(changed))
    return jsonify(changed=changed)

@app.delete('/api/manual/<ident>')
@auth(['admin','logist'])
def delete_manual(ident):
    with LOCK,db() as c:
        ws.edit_record(c,ident,request.get_json(silent=True) or {},user(),delete=True);audit(c,'delete record',ident)
    return jsonify(ok=True)

@app.get('/api/users')
@auth(['admin'])
def users():
    with db() as c:rows=[dict(r) for r in c.execute('select id,name,role,vehicles from users')]
    return jsonify(rows)
@app.post('/api/users')
@auth(['admin'])
def add_user():
    b = request.get_json()
    ws.body(b)
    role = b.get('role')
    name = str(b.get('name', '')).strip()
    pwd = str(b.get('password', ''))
    cars = b.get('vehicles', [])
    if role not in ('admin', 'logist', 'viewer') or not name or len(pwd) < 12:
        raise ValueError('Имя обязательно, пароль — от 12 символов')
    if not isinstance(cars, list):
        raise ValueError('Неизвестная машина')
    try:
        with db() as c:
            if cars:
                catalog = ws.catalogs(c)['vehicles']
                known = {row['name'] for row in catalog if not row.get('merged_into')}
                if any(not isinstance(car, str) or car not in known for car in cars):
                    raise ValueError('Неизвестная машина')
            c.execute('insert into users(name,password,role,vehicles) values(?,?,?,?)',
                      (name, generate_password_hash(pwd), role, json.dumps(cars)))
            audit(c, 'add user', name)
    except sqlite3.IntegrityError:
        raise ValueError('Пользователь уже существует')
    return jsonify(ok=True)
@app.get('/api/audit')
@auth(['admin'])
def get_audit():
    with db() as c:return jsonify([dict(r) for r in c.execute('select * from audit order by id desc limit 100')])
@app.get('/api/connections')
@auth()
def connections():
    p=DATA/'connections.json'
    from app.connections import SOURCES,with_authorization
    rows=json.loads(p.read_text()) if p.exists() else [{k:v for k,v in s.items() if k!='probe'} for s in SOURCES]
    return jsonify(with_authorization(rows,DATA))
@app.post('/api/connections/check')
@auth(['admin'])
def check_connections():
    from app.connections import check_all,with_authorization
    results=with_authorization(check_all(),DATA)
    p=DATA/'connections.json';p.write_text(json.dumps(results,ensure_ascii=False,indent=2));os.chmod(p,0o600)
    with db() as c:audit(c,'check connections','Read-only network checks')
    return jsonify(results)
@app.get('/api/transtrade')
@auth(['admin'])
def transtrade_status():
    from app.transtrade import configured,status,reconciliation_status,LIMITATIONS
    with db() as c:
        state=status(c);history=reconciliation_status(c);r=c.execute("select body from workspace_meta where key='transtrade_runs'").fetchone()
    return jsonify(configured=configured(DATA),snapshot=state,reconciliation=history,limitations=LIMITATIONS,periods=json.loads(r[0]) if r else [])

@app.post('/api/transtrade/reconcile')
@auth(['admin'])
def transtrade_reconcile():
    from app.transtrade import reconcile
    ws.body(request.get_json())
    result=reconcile(DATA,DB,force=True)
    if result['status']=='error':return jsonify(error=result['error']),400
    if result['status']=='busy':return jsonify(error=result['reason']),409
    with db() as c:audit(c,'reconcile transtrade',f"История: {result['processed']} заявок, найдено по ID: {result['discovered_by_id']}")
    return jsonify(result)

@app.post('/api/transtrade/sync')
@auth(['admin'])
def transtrade_sync():
    from app.transtrade import sync
    body=request.get_json();ws.body(body)
    result=sync(DATA,DB,body.get('from'),body.get('to'))
    with db() as c:audit(c,'sync transtrade',f"{result['start']} — {result['end']}: {result['received']} заявок")
    return jsonify(result)

@app.get('/api/neftm')
@auth(['admin'])
def neftm_snapshot():
    from app.neftm import snapshot
    return jsonify(configured=(DATA/'neftm-api.key').exists(),snapshot=snapshot(DATA))

@app.get('/api/fuel-history/<provider>')
@auth(['admin'])
def fuel_period_snapshot(provider):
    from app.fuel_history import snapshot_for_period
    return jsonify(snapshot_for_period(DATA,provider,request.args.get('from'),request.args.get('to')))

@app.post('/api/neftm/sync')
@auth(['admin'])
def neftm_sync():
    from app.neftm import sync
    body=request.get_json()
    if not isinstance(body,dict):raise ValueError('Укажите период загрузки.')
    result=sync(DATA,body.get('from'),body.get('to'))
    with db() as c:audit(c,'sync neftm',f"{result['from']} — {result['to']}: {len(result['rows'])} транзакций")
    return jsonify(result)

@app.get('/api/rosneft')
@auth(['admin'])
def rosneft_snapshot():
    from app.rosneft import snapshot, configured
    return jsonify(configured=configured(DATA), snapshot=snapshot(DATA))

@app.route('/api/rosneft/driver-assignments', methods=['GET', 'PUT'])
@auth(['admin'])
def rosneft_driver_assignments():
    from app.demo_data import enabled
    from app.fuel_history import read
    from app import rosneft_drivers

    if enabled():
        abort(404)
    with db() as c:
        c.execute('BEGIN IMMEDIATE' if request.method == 'PUT' else 'BEGIN')
        cards = read(DATA, 'rosneft').get('cards', [])
        if request.method == 'PUT':
            body = request.get_json()
            rosneft_drivers.assign(c, body, cards)
            audit(c, 'assign rosneft driver', f"{body['card'][-4:]}: {body['driver_id']} {body['start']}")
        history = rosneft_drivers.timeline(c)
        drivers = rosneft_drivers.drivers(c)
        return jsonify(
            today=ws.today(),
            cards=[dict(card=row['Num'], note=row['Rem'], history=[
                dict(event, driver=drivers.get(event['driver_id'], {}).get('name', ''))
                for event in history[row['Num']]
            ]) for row in cards],
            drivers=sorted(
                [dict(id=ident, name=row['name']) for ident, row in drivers.items()
                 if rosneft_drivers.selectable(row)], key=lambda row: row['name']
            ),
        )


@app.post('/api/rosneft/sync')
@auth(['admin'])
def rosneft_sync():
    from app.rosneft import sync
    body = request.get_json()
    if not isinstance(body, dict):
        raise ValueError('Укажите период загрузки.')
    result = sync(DATA, body.get('from'), body.get('to'), db_path=DB)
    with db() as c:
        audit(c, 'sync rosneft', f"{result['from']} — {result['to']}: {len(result['rows'])} операций")
    return jsonify(result)

@app.get('/api/monitoring')
@auth(['admin'])
def monitoring_snapshot():
    from app.monitoring import snapshot,configured
    return jsonify(configured=configured(DATA),snapshot=snapshot(DATA))

@app.post('/api/monitoring/sync')
@auth(['admin'])
def monitoring_sync():
    from app.monitoring import sync
    result=sync(DATA)
    with db() as c:audit(c,'sync monitoring',f"{len(result['rows'])} объектов")
    return jsonify(result)

@app.get('/api/monitoring/history')
@auth(['admin'])
def monitoring_history():
    from app.monitoring_history import daily_rows,mappings,job_status
    names=dataset()['vehicles']
    rows=daily_rows(DATA,names)
    return jsonify(rows=rows,mappings=mappings(DATA,names),job=job_status(DATA))

@app.post('/api/monitoring/history/sync')
@auth(['admin'])
def monitoring_history_sync():
    from app.monitoring_history import start
    body=request.get_json()
    if not isinstance(body,dict) or type(body.get('refresh',False)) is not bool:
        raise ValueError('Укажите период загрузки истории.')
    result=start(DATA,dataset()['vehicles'],body.get('from'),body.get('to'),body.get('refresh',False))
    with db() as c:audit(c,'sync monitoring history',f"{result['from']} — {result['to']}")
    return jsonify(result),202

from app.refresh import register as register_refresh
refresh_service = register_refresh(app, auth, DATA, DB, dataset)

@app.get('/healthz')
def health_check():
    # No accounts, provider payloads or credentials in the operational endpoint.
    from app.health import read_worker_health
    worker=read_worker_health(DATA)
    expected=os.environ.get('FLEET_SCHEDULER','embedded')!='disabled'
    healthy=worker['healthy'] if expected else True
    return jsonify(status='ok' if healthy else 'degraded',web='ok',updates='ok' if worker['healthy'] else 'unavailable'),200 if healthy else 503

from app.charter import register as register_charter
register_charter(app,db,dataset,auth,user,audit,LOCK,DATA)

from app.evidence_routes import register as register_evidence
register_evidence(app,db,dataset,auth,audit,LOCK)

if __name__=='__main__':
    from waitress import serve
    init()
    if os.environ.get('FLEET_SCHEDULER','embedded')=='embedded':refresh_service.start_scheduler()
    try:
        serve(app,**waitress_options())
    finally:
        refresh_service.stop()
