"""Real process death between business commit and queue checkpoint, isolated DB."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

from app import workspace
from tests.test_workspace import source


SCRIPT = r'''
import json,os,signal,sqlite3,sys,threading,time
from pathlib import Path
from app import autosync,refresh,transtrade,worker,alerts
folder=Path(sys.argv[1]);mode=sys.argv[2]
service=refresh.RefreshService(folder,folder/'fleet.sqlite',lambda:{'vehicles':[]})
autosync.Scheduler._configured=lambda self,source:source=='transtrade'
autosync.Scheduler._history=lambda self,source:{'message':'test history','pending_days':0}
alerts.observe=lambda *a,**k:None
def current(self,source):
    path=folder/'attempts.json'
    count=json.loads(path.read_text()) if path.exists() else 0
    path.write_text(json.dumps(count+1))
    raw=dict(ID='1',BeginDateTime='2026-08-01 08:00:00',EndDateTime='2026-08-01 12:00:00',ClientSum='1000',WorkerSum='400')
    with sqlite3.connect(folder/'fleet.sqlite') as c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE')
        transtrade.apply(c,[raw],'2026-08-01','2026-08-31')
    (folder/'committed').write_text('yes')
    if mode=='hang':
        while True:time.sleep(.1)
    return {'message':'test applied'}
autosync.Scheduler._current=current
stopped=threading.Event()
signal.signal(signal.SIGTERM,lambda *_:stopped.set())
raise SystemExit(worker.supervise(service,stopped,poll_seconds=.05,join_timeout=1))
'''


def wait_for(fn):
    until=time.monotonic()+8
    while time.monotonic()<until:
        try:
            if fn():return
        except (FileNotFoundError,KeyError):pass
        time.sleep(.02)
    raise AssertionError('Subprocess did not reach the expected state')


def test_killed_worker_replays_committed_order_without_duplicates(tmp_path,source):
    db=tmp_path/'fleet.sqlite'
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row;workspace.initialize(c,source)
    python=sys.executable
    def start(mode):
        return subprocess.Popen([python,'-c',SCRIPT,str(tmp_path),mode],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    first=start('hang')
    try:
        wait_for(lambda:(tmp_path/'committed').exists())
        first.kill();first.wait(3)
        with sqlite3.connect(db) as c:
            committed=c.execute("select id,body,revision from records where kind='trips'").fetchall()
        saved=json.loads((tmp_path/'refresh-auto.json').read_text())
        assert saved['tasks']['transtrade:current']['status']=='running'
        second=start('success')
        try:
            wait_for(lambda:json.loads((tmp_path/'refresh-auto.json').read_text())['tasks']['transtrade:current']['status']=='success')
            with sqlite3.connect(db) as c:
                assert c.execute("select id,body,revision from records where kind='trips'").fetchall()==committed
            assert json.loads((tmp_path/'attempts.json').read_text())==2
        finally:
            second.terminate();second.wait(4)
        third=start('success')
        try:
            wait_for(lambda:json.loads((tmp_path/'refresh-heartbeat.json').read_text())['pid']==third.pid)
            assert json.loads((tmp_path/'attempts.json').read_text())==2
        finally:
            third.terminate();third.wait(4)
    finally:
        if first.poll() is None:first.kill();first.wait(3)
