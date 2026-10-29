import datetime as dt, functools, hashlib, io, json, os, secrets, sqlite3, threading, zipfile
from pathlib import Path
from flask import Flask,request,jsonify,session,send_from_directory,redirect,abort
from werkzeug.security import generate_password_hash,check_password_hash
from app.importer import load_excel,vehicle,SOURCE
from app.analytics import report,reconcile
from app import workspace as ws
ROOT=Path(__file__).resolve().parent.parent
DATA=Path(os.environ.get('FLEET_DATA',ROOT/'data'));DATA.mkdir(exist_ok=True,parents=True);os.chmod(DATA,0o700)
DB=DATA/'fleet.sqlite'
app=Flask(__name__,static_folder='static');app.config.update(MAX_CONTENT_LENGTH=25*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=12),TRUSTED_HOSTS=['127.0.0.1','localhost'])
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
        if not c.execute('select 1 from users').fetchone():
            pwd=secrets.token_urlsafe(18);c.execute('insert into users(name,password,role,vehicles) values(?,?,?,?)',('Руководитель',generate_password_hash(pwd),'admin','[]'))
            (DATA/'local-login.txt').write_text('Пользователь: Руководитель\nПароль: '+pwd+'\n');os.chmod(DATA/'local-login.txt',0o600)
        if not c.execute('select 1 from snapshot').fetchone():c.execute('insert into snapshot values(1,?)',(json.dumps(load_excel(),ensure_ascii=False),))
    with db() as c:
        # Snapshot backup before the first non-destructive workspace migration.
        if not c.execute("select 1 from sqlite_master where name='workspace_meta'").fetchone():
            backup=DATA/'before-workspace-v2.sqlite'
            if not backup.exists():
                with sqlite3.connect(backup) as target:c.backup(target)
                os.chmod(backup,0o600)
        original=json.loads(c.execute('select body from snapshot where id=1').fetchone()[0])
        if not c.execute("select 1 from sqlite_master where name='workspace_meta'").fetchone():
            # Enrich only from the exact original files; never replace current financial rows.
            if all((SOURCE/f['name']).exists() and hashlib.sha256((SOURCE/f['name']).read_bytes()).hexdigest()==f['sha256'] for f in original['meta']['files']):
                enriched=load_excel();original['vehicle_details']=enriched.get('vehicle_details',{})
                extra={r['source']:r for r in enriched['satellite']}
                original['satellite']=[dict(r,**{k:v for k,v in extra.get(r['source'],{}).items() if k not in r}) for r in original['satellite']]
        ws.initialize(c,original,c.execute('select * from manual').fetchall())
    os.chmod(DB,0o600)
    if not (DATA/'bootstrap.used').exists() and not (DATA/'bootstrap.token').exists():(DATA/'bootstrap.token').write_text(secrets.token_urlsafe(32));os.chmod(DATA/'bootstrap.token',0o600)
def audit(c,action,detail):c.execute('insert into audit(at,user_id,action,detail) values(?,?,?,?)',(dt.datetime.now(dt.timezone.utc).isoformat(),session.get('uid'),action,detail))
def user():
    with db() as c:r=c.execute('select id,name,role,vehicles from users where id=?',(session.get('uid'),)).fetchone()
    if not r:return None
    u=dict(r)
    with db() as c:cats=ws.catalogs(c)
    u['vehicles']=[(ws.lookup(cats,'vehicles',v) or {'name':v})['name'] for v in json.loads(u['vehicles'])];return u
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
def dataset():
    with db() as c:d=ws.dataset(c)
    from app.monitoring_history import daily_rows,merge_satellite
    names={name for r in d['directories']['vehicles'] for name in [r['name'],*r.get('aliases',[])]}
    history=daily_rows(DATA,names)
    for row in history:ws.resolve_row(row,d['directories'])
    d['satellite_raw']=d['satellite']
    if history:
        d['satellite']=merge_satellite(d['satellite'],history)
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

@app.delete('/api/workspace/<kind>/<ident>')
@auth(['admin'])
def extra_delete(kind,ident):
    if kind not in ('coverage','card_bindings','expenses'):abort(404)
    with LOCK,db() as c:
        if kind=='coverage':c.execute('delete from coverage where id=?',(ident,))
        else:c.execute('update '+kind+' set deleted=1,revision=revision+1 where id=?',(ident,))
        audit(c,'remove '+kind,ident)
    return jsonify(ok=True)

@app.after_request
def headers(r):
    r.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"});return r
@app.errorhandler(ValueError)
def bad(e):return jsonify(error=str(e)),400
@app.errorhandler(413)
def large(e):return jsonify(error='Файл больше 25 МБ'),413
@app.get('/')
def index():return send_from_directory(app.static_folder,'index.html')
@app.get('/<section>/<page>')
def page(section,page):
    if section=='integrations' and page=='axenta':return redirect('/integrations/monitoring',code=302)
    pages={'analytics':{'dashboard','statistics','comparison','reconcile','planreport','downtime','economics','telemetry'},'planning':{'calendar','planner'},'data':{'orders','directories','connections','users','quality','coverage','fuelcards','expenses'},'integrations':{'neftm','monitoring','rosneft','transtrade'}}
    if page not in pages.get(section,set()):abort(404)
    return send_from_directory(app.static_folder,'index.html')
@app.get('/bootstrap/<token>')
def bootstrap(token):
    p=DATA/'bootstrap.token'
    if request.remote_addr!='127.0.0.1' or not p.exists() or not secrets.compare_digest(token,p.read_text()):abort(403)
    session.clear();session.update(uid=1,csrf=secrets.token_hex(24));session.permanent=True;p.unlink();(DATA/'bootstrap.used').touch(mode=0o600);return redirect('/')
FAILURES={}
@app.post('/api/login')
def login():
    if request.headers.get('Origin') not in (None,request.host_url.rstrip('/')):abort(403)
    now=dt.datetime.now().timestamp();ip=request.remote_addr;history=[x for x in FAILURES.get(ip,[]) if now-x<300]
    if len(history)>=10:return jsonify(error='Слишком много попыток. Повторите через 5 минут'),429
    b=request.get_json();
    with db() as c:u=c.execute('select * from users where name=?',(b.get('name'),)).fetchone()
    if not u or not check_password_hash(u['password'],str(b.get('password',''))):FAILURES[ip]=history+[now];return jsonify(error='Неверный логин или пароль'),401
    session.clear();session.update(uid=u['id'],csrf=secrets.token_hex(24));session.permanent=True;return jsonify(ok=True)
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
def validate_day(v):return dt.date.fromisoformat(v).isoformat()
def allowed_car(u,car):return u['role']=='admin' or car in u['vehicles']
@app.post('/api/manual/<kind>')
@auth(['admin','logist'])
def create_manual(kind):
    if kind not in ('statuses','plans','trips'):abort(404)
    with LOCK,db() as c:
        created=ws.create_records(c,kind,request.get_json(),user());audit(c,'create '+kind,str(created))
    return jsonify(created=created)

@app.delete('/api/manual/<ident>')
@auth(['admin','logist'])
def delete_manual(ident):
    with LOCK,db() as c:
        ws.edit_record(c,ident,{},user(),delete=True);audit(c,'delete record',ident)
    return jsonify(ok=True)

@app.post('/api/import')
@auth(['admin'])
def import_excel():
    with LOCK:
        if request.files:
            if not all(k in request.files for k in ('statistics','planner')):raise ValueError('Выберите обе книги')
            files={k:request.files[k].read() for k in ('statistics','planner')}
            for v in files.values():
                try:
                    z=zipfile.ZipFile(io.BytesIO(v))
                    if sum(x.file_size for x in z.infolist())>150*1024*1024:raise ValueError('Слишком большая распакованная книга')
                except zipfile.BadZipFile:raise ValueError('Ожидается файл XLSX')
            import tempfile
            with tempfile.TemporaryDirectory(dir=DATA) as tmp:
                a=Path(tmp)/'Статистика.xlsx';b=Path(tmp)/'Планировщик.xlsx';a.write_bytes(files['statistics']);b.write_bytes(files['planner']);d=load_excel(a,b)
        else:d=load_excel()
        with db() as c:
            previous=c.execute('select body from snapshot where id=1').fetchone()[0]
            backup=DATA/('snapshot-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json');backup.write_text(previous);os.chmod(backup,0o600)
            ws.ingest(c,d)
            c.execute('update snapshot set body=? where id=1',(json.dumps(d,ensure_ascii=False),));audit(c,'import',json.dumps(d['meta']['counts']))
    return jsonify(meta=d['meta'])
@app.get('/api/users')
@auth(['admin'])
def users():
    with db() as c:rows=[dict(r) for r in c.execute('select id,name,role,vehicles from users')]
    return jsonify(rows)
@app.post('/api/users')
@auth(['admin'])
def add_user():
    b=request.get_json();role=b.get('role');name=str(b.get('name','')).strip();pwd=str(b.get('password',''));cars=b.get('vehicles',[])
    if role not in ('admin','logist','viewer') or not name or len(pwd)<12:raise ValueError('Имя обязательно, пароль — от 12 символов')
    if not isinstance(cars,list) or any(v not in dataset()['vehicles'] for v in cars):raise ValueError('Неизвестная машина')
    try:
        with db() as c:c.execute('insert into users(name,password,role,vehicles) values(?,?,?,?)',(name,generate_password_hash(pwd),role,json.dumps(cars)));audit(c,'add user',name)
    except sqlite3.IntegrityError:raise ValueError('Пользователь уже существует')
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
    from app.transtrade import configured,status,LIMITATIONS
    with db() as c:
        state=status(c);r=c.execute("select body from workspace_meta where key='transtrade_runs'").fetchone()
    return jsonify(configured=configured(DATA),snapshot=state,limitations=LIMITATIONS,periods=json.loads(r[0]) if r else [])

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

@app.post('/api/rosneft/sync')
@auth(['admin'])
def rosneft_sync():
    from app.rosneft import sync
    body = request.get_json()
    if not isinstance(body, dict):
        raise ValueError('Укажите период загрузки.')
    result = sync(DATA, body.get('from'), body.get('to'))
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

if __name__=='__main__':
    from waitress import serve
    init();serve(app,host='127.0.0.1',port=int(os.environ.get('PORT',8765)),threads=6)
