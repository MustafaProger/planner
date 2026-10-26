import datetime as dt, functools, hashlib, io, json, os, secrets, sqlite3, threading, zipfile
from pathlib import Path
from flask import Flask,request,jsonify,session,send_from_directory,redirect,abort
from werkzeug.security import generate_password_hash,check_password_hash
from app.importer import load_excel,vehicle,SOURCE
from app.analytics import report,reconcile
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
    os.chmod(DB,0o600)
    if not (DATA/'bootstrap.used').exists() and not (DATA/'bootstrap.token').exists():(DATA/'bootstrap.token').write_text(secrets.token_urlsafe(32));os.chmod(DATA/'bootstrap.token',0o600)
def audit(c,action,detail):c.execute('insert into audit(at,user_id,action,detail) values(?,?,?,?)',(dt.datetime.now(dt.timezone.utc).isoformat(),session.get('uid'),action,detail))
def user():
    with db() as c:r=c.execute('select id,name,role,vehicles from users where id=?',(session.get('uid'),)).fetchone()
    if not r:return None
    u=dict(r);u['vehicles']=json.loads(u['vehicles']);return u
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
    with db() as c:
        d=json.loads(c.execute('select body from snapshot where id=1').fetchone()[0]);ms=c.execute('select id,kind,body from manual where deleted=0').fetchall()
    for m in ms:
        b=json.loads(m['body']);b['id']=m['id'];b['source']='Введено в приложении';d[m['kind']].append(b)
    return d
@app.after_request
def headers(r):
    r.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"});return r
@app.errorhandler(ValueError)
def bad(e):return jsonify(error=str(e)),400
@app.errorhandler(413)
def large(e):return jsonify(error='Файл больше 25 МБ'),413
@app.get('/')
def index():return send_from_directory(app.static_folder,'index.html')
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
def data():return jsonify(dataset())
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
    if kind not in ('statuses','plans'):abort(404)
    b=request.get_json();d=dataset();u=user();start=dt.date.fromisoformat(b.get('date',''));end=dt.date.fromisoformat(b.get('end_date',b.get('date','')))
    if not 0<=(end-start).days<=366:raise ValueError('Период должен быть от 1 до 367 дней')
    records=[]
    if kind=='statuses':
        k=b.get('kind');entity=b.get('entity','');reason=b.get('reason','').strip()
        if k not in ('vehicle','driver') or entity not in d['vehicles' if k=='vehicle' else 'drivers']:raise ValueError('Выберите машину или водителя из справочника')
        if reason not in ['Отпуск','Больничный','Выходной','Сервис','Ремонт','Нет заявки','Пересменка','БезВодителя','Другое']:raise ValueError('Выберите причину простоя')
        authorized=allowed_car(u,entity) if k=='vehicle' else u['role']=='admin' or any(r['driver']==entity and r['vehicle'] in u['vehicles'] for r in d['trips']+d['plans'])
        if not authorized:abort(403)
        base=dict(kind=k,entity=entity,reason=reason,note=str(b.get('note',''))[:1000])
    else:
        car=b.get('vehicle');driver=b.get('driver');route=next((r for r in d['routes'] if r['id']==b.get('route')),None)
        if car not in d['vehicles'] or driver not in d['drivers'] or not route:raise ValueError('Выберите машину, водителя и маршрут из справочников')
        if not allowed_car(u,car):abort(403)
        partner=d['drivers'][driver]=='Партнёр';base=dict(vehicle=car,driver=driver,route=route['id'],revenue=route['revenue'],payout=route['partner_payout'] if partner else route['payout'],km=route['km'],hours=route['hours'],partner=partner)
    weekdays=b.get('weekdays',list(range(7)))
    if not isinstance(weekdays,list) or not all(type(x)==int and 0<=x<=6 for x in weekdays):raise ValueError('Некорректные дни недели')
    for n in range((end-start).days+1):
        day=start+dt.timedelta(days=n)
        if day.weekday() not in weekdays:continue
        r=dict(base,date=day.isoformat())
        keys=['date','kind','entity','reason'] if kind=='statuses' else ['date','vehicle','driver','route']
        if any(all(old.get(k)==r[k] for k in keys) for old in d[kind]):continue
        records.append(r)
    with LOCK,db() as c:
        for r in records:
            fingerprint=hashlib.sha256((kind+json.dumps({k:r[k] for k in keys},sort_keys=True)).encode()).hexdigest()
            c.execute('insert into manual(id,kind,body,created_by) values(?,?,?,?) ON CONFLICT(id) DO UPDATE SET deleted=0,body=excluded.body,created_by=excluded.created_by',(fingerprint,kind,json.dumps(r,ensure_ascii=False),u['id']))
        audit(c,'create '+kind,str(len(records)))
    return jsonify(created=len(records))
@app.delete('/api/manual/<ident>')
@auth(['admin','logist'])
def delete_manual(ident):
    with db() as c:
        r=c.execute('select * from manual where id=? and deleted=0',(ident,)).fetchone()
        if not r:abort(404)
        if user()['role']!='admin' and r['created_by']!=user()['id']:abort(403)
        c.execute('update manual set deleted=1 where id=?',(ident,));audit(c,'delete manual',ident)
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
    from app.connections import SOURCES
    return jsonify(json.loads(p.read_text()) if p.exists() else [{k:v for k,v in s.items() if k!='probe'} for s in SOURCES])
@app.post('/api/connections/check')
@auth(['admin'])
def check_connections():
    from app.connections import check_all
    results=check_all()
    p=DATA/'connections.json';p.write_text(json.dumps(results,ensure_ascii=False,indent=2));os.chmod(p,0o600)
    with db() as c:audit(c,'check connections','Read-only network checks')
    return jsonify(results)
if __name__=='__main__':
    from waitress import serve
    init();serve(app,host='127.0.0.1',port=int(os.environ.get('PORT',8765)),threads=6)
