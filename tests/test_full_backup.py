"""Full backups preserve private data and restore services on failed captures."""
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile
import pytest
from deploy import full_backup as b

@pytest.fixture
def data(tmp_path):
    folder=tmp_path/'fleet';folder.mkdir(mode=0o700)
    with sqlite3.connect(folder/'fleet.sqlite') as c:
        c.executescript("create table users(id integer primary key,password text);insert into users values(1,'hash-test');create table records(id text primary key,body text,deleted integer);insert into records values('one','{\"amount\":100}',0);insert into records values('deleted','{}',1);create table custom_history(id integer,body blob);insert into custom_history values(1,x'010203');")
    for name,value in {'session.key':'session-test','bootstrap.used':'','neftm-api.key':'private-test','monitoring-session.json':'"private-session-test"','monitoring-history.json':'{"cells":{"test":1}}','refresh-auto.json':'{"tasks":{"monitoring:history":{"status":"interrupted"}}}'}.items():
        (folder/name).write_text(value)
    for name in ['refresh-heartbeat.json','refresh-scheduler.lock','server.pid','old.sqlite-wal']:(folder/name).write_text('runtime')
    for path in folder.iterdir():path.chmod(0o600)
    return folder

@pytest.fixture
def dest(tmp_path):
    folder=tmp_path/'backup';folder.mkdir(mode=0o700);return folder


def contents(data):return {p.name:p.read_bytes() for p in data.iterdir() if p.is_file()}


def test_full_snapshot_restores_tables_secrets_session_and_history(data,dest):
    before=contents(data)
    result=b.full_backup(data,dest,writers_stopped=True)
    assert contents(data)==before
    archive=Path(result['path']);assert archive.stat().st_mode&0o777==0o600
    manifest=b.verify_archive(archive,dest)
    assert manifest['tables']=={'users':1,'records':2,'custom_history':1}
    with tarfile.open(archive) as tar:
        for name in ['session.key','bootstrap.used','neftm-api.key','monitoring-session.json','monitoring-history.json','refresh-auto.json']:
            assert tar.extractfile('data/'+name).read()==before[name]
            assert manifest['files'][name]['sha256']==hashlib.sha256(before[name]).hexdigest()
        for name in ['server.pid','refresh-heartbeat.json','refresh-scheduler.lock','old.sqlite-wal']:
            assert 'data/'+name not in tar.getnames()
    second=b.full_backup(data,dest,writers_stopped=True)
    assert second['path']!=result['path'] and archive.exists()
    assert len(list(dest.glob('fleet-*.tar.gz')))==2
    assert not list(dest.glob('.fleet-stage-*')) and not list(dest.glob('.fleet-restore-*'))


def test_requires_stopped_boundary_and_private_destination(data,dest):
    with pytest.raises(ValueError,match='Stop writers'):b.full_backup(data,dest)
    dest.chmod(0o755)
    with pytest.raises(ValueError,match='private'):b.full_backup(data,dest,writers_stopped=True)
    assert not list(dest.glob('*.gz'))


def test_active_writer_lock_refuses_snapshot(data,dest):
    with (data/'refresh-scheduler.lock').open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='still active'):b.full_backup(data,dest,writers_stopped=True)
    assert not list(dest.glob('*.gz'))


class Controller:
    def __init__(self,worker='active',web='active'):
        self.states={'fleet-worker.service':worker,'fleet-web.service':web};self.events=[]
    def state(self,unit):return {'LoadState':'loaded','ActiveState':self.states[unit],'MainPID':'123' if self.states[unit]=='active' else '0'}
    def stop(self):self.events.append('stop');self.states={k:'inactive' for k in self.states}
    def restore(self,running):
        self.events.append(('restore',tuple(running)))
        for unit in running:self.states[unit]='active'


def test_stopped_capture_then_restart_before_compression(data,dest,monkeypatch):
    control=Controller();original_capture=b.capture;original_verify=b.verify_archive
    def capture(*args):
        assert all(v=='inactive' for v in control.states.values());control.events.append('capture')
        return original_capture(*args)
    def verify(*args):
        assert all(v=='active' for v in control.states.values());control.events.append('verify')
        return original_verify(*args)
    monkeypatch.setattr(b,'capture',capture);monkeypatch.setattr(b,'verify_archive',verify)
    b.full_backup(data,dest,systemd=control)
    assert control.events==['stop','capture',('restore',b.UNITS),'verify']


@pytest.mark.parametrize('error',[ValueError('copy failed'),KeyboardInterrupt()])
def test_restart_finally_on_capture_failure_or_signal(data,dest,monkeypatch,error):
    control=Controller()
    def fail(*args):raise error
    monkeypatch.setattr(b,'capture',fail)
    with pytest.raises(type(error)):b.full_backup(data,dest,systemd=control)
    assert control.events==['stop',('restore',b.UNITS)]
    assert all(v=='active' for v in control.states.values()) and not list(dest.glob('*.gz'))


def test_inconsistent_worker_state_does_not_change_services(data,dest):
    control=Controller(worker='inactive')
    with pytest.raises(RuntimeError,match='reconcile service state'):b.full_backup(data,dest,systemd=control)
    assert control.events==[] and control.states['fleet-worker.service']=='inactive'


def test_originally_inactive_web_not_started(data,dest):
    control=Controller(web='inactive')
    b.full_backup(data,dest,systemd=control)
    assert control.events[-1]==('restore',('fleet-worker.service',))
    assert control.states['fleet-web.service']=='inactive'


def test_failed_partial_stop_restores_services(data,dest):
    class Failed(Controller):
        def stop(self):super().stop();raise RuntimeError('stop failed')
    control=Failed()
    with pytest.raises(RuntimeError):b.full_backup(data,dest,systemd=control)
    assert control.events[-1]==('restore',b.UNITS)


def test_corrupt_archive_not_published(data,dest,monkeypatch):
    before=contents(data)
    def fail(*args):raise ValueError('restored checksum')
    monkeypatch.setattr(b,'verify_archive',fail)
    with pytest.raises(ValueError):b.full_backup(data,dest,writers_stopped=True)
    assert contents(data)==before and not list(dest.glob('*.tar.gz'))


def test_symlink_rejected_and_source_unchanged(data,dest,tmp_path):
    other=tmp_path/'other-private';other.write_text('other app')
    (data/'wrong-link').symlink_to(other)
    with pytest.raises(ValueError,match='Symlinks'):b.full_backup(data,dest,writers_stopped=True)
    assert other.read_text()=='other app' and not list(dest.glob('*.tar.gz'))


def test_changed_json_detected_during_capture(data,dest,monkeypatch):
    original=b.shutil.copyfile
    def changing(src,target):
        result=original(src,target)
        if Path(src).name=='monitoring-history.json':Path(src).write_text('{"changed":true}')
        return result
    monkeypatch.setattr(b.shutil,'copyfile',changing)
    with pytest.raises(ValueError,match='changed during'):b.full_backup(data,dest,writers_stopped=True)
    assert not list(dest.glob('*.tar.gz'))


def test_units_target_only_own_data_and_moscow_time():
    root=Path(__file__).resolve().parents[1]
    service=(root/'deploy/fleet-backup.service').read_text();timer=(root/'deploy/fleet-backup.timer').read_text()
    assert '--quiesce-systemd' in service and '/var/backups/fleet-analytics' in service
    assert 'OnCalendar=*-*-* 03:15:00 Europe/Moscow' in timer
    assert 'Persistent=false' in timer
    assert b.UNITS==('fleet-worker.service','fleet-web.service')


def test_restore_checks_real_tampered_payload(data,dest):
    import io
    result=b.full_backup(data,dest,writers_stopped=True)
    tampered=dest/'tampered.tar.gz'
    with tarfile.open(result['path']) as source,tarfile.open(tampered,'w:gz') as changed:
        for member in source.getmembers():
            raw=source.extractfile(member).read()
            if member.name=='data/monitoring-history.json':raw=b'{"cells":{"wrong":999}}'
            member.size=len(raw);changed.addfile(member,io.BytesIO(raw))
    with pytest.raises(ValueError,match='checksum'):b.verify_archive(tampered,dest)
    assert not list(dest.glob('.fleet-restore-*'))


def test_database_values_and_deleted_history_survive(data,dest,tmp_path):
    result=b.full_backup(data,dest,writers_stopped=True)
    restored=tmp_path/'restored.sqlite'
    with tarfile.open(result['path']) as tar:restored.write_bytes(tar.extractfile('data/fleet.sqlite').read())
    with sqlite3.connect(restored) as c:
        assert c.execute('select * from users').fetchall()==[(1,'hash-test')]
        assert c.execute('select * from records order by id').fetchall()==[('deleted','{}',1),('one','{"amount":100}',0)]
        assert c.execute('select body from custom_history').fetchone()[0]==b'\x01\x02\x03'
