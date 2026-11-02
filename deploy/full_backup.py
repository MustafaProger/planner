#!/usr/bin/env python3
"""Private full Fleet backup; no retention deletion, remote storage or notifications.

Use --quiesce-systemd on the fleet host, or --writers-stopped after stopping all
writers yourself. Only the two named Fleet services are controlled. A staged
snapshot is captured while stopped; compression and restore verification happen
after service restart, keeping the interruption short.
"""
import argparse
from contextlib import contextmanager, ExitStack
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import tempfile
import uuid

UNITS = ('fleet-worker.service', 'fleet-web.service')
RUNTIME = {'refresh-heartbeat.json', 'server.pid'}


def _private_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError('Use an existing absolute private directory.')
    if path.stat().st_mode & 0o077:
        raise ValueError('Directory must have private permissions (0700).')
    return path


def _connect(path):
    c = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=30)
    c.execute('pragma query_only=ON')
    return c


def _tables(c):
    return {name: c.execute('select count(*) from "'+name.replace('"','""')+'"').fetchone()[0]
            for (name,) in c.execute("select name from sqlite_master where type='table' order by name")}


def _hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def _inventory(data):
    files = []
    for path in sorted(data.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks are not allowed in the Fleet data snapshot.')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Only regular Fleet data files can be backed up.')
        rel = path.relative_to(data).as_posix()
        if rel in RUNTIME or path.name.endswith(('.lock', '.pid', '.log', '-wal', '-shm', '-journal')):
            continue
        files.append(rel)
    return files


@contextmanager
def _writer_locks(data):
    # Lock existing provider/scheduler files without creating or editing data.
    with ExitStack() as stack:
        for path in sorted(data.glob('*.lock')):
            if path.is_symlink():
                raise ValueError('Unexpected lock symlink.')
            handle = stack.enter_context(path.open('rb'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('A Fleet writer is still active; backup was not taken.') from None
        yield


class Systemd:
    def _run(self, *args):
        try:
            result = subprocess.run(['/bin/systemctl', *args], capture_output=True, text=True, timeout=100, check=True)
        except (subprocess.SubprocessError, OSError):
            raise RuntimeError('Could not control Fleet services; inspect their systemd status.') from None
        return result.stdout

    def state(self, unit):
        result = self._run('show', unit, '--property=LoadState,ActiveState,MainPID')
        fields = dict(line.split('=', 1) for line in result.splitlines() if '=' in line)
        if fields.get('LoadState') != 'loaded':
            raise RuntimeError('Both Fleet service units must be installed before scheduled backup.')
        return fields

    def stop(self):
        self._run('stop', *UNITS)

    def restore(self, running):
        if running:
            self._run('start', *running)


@contextmanager
def stopped_services(control):
    before = {unit: control.state(unit) for unit in UNITS}
    allowed = {'active', 'inactive', 'failed'}
    if any(state.get('ActiveState') not in allowed for state in before.values()):
        raise RuntimeError('Fleet services are changing state; retry backup after they settle.')
    # The web unit Wants=worker. Avoid waking an originally stopped worker
    # indirectly, and never bypass systemd's dependency ordering.
    if before['fleet-web.service']['ActiveState']=='active' and before['fleet-worker.service']['ActiveState']!='active':
        raise RuntimeError('Worker is not active while web is active; reconcile service state before backup.')
    running = [unit for unit in UNITS if before[unit]['ActiveState'] == 'active']
    try:
        control.stop()
        after = {unit: control.state(unit) for unit in UNITS}
        if any(state.get('ActiveState') not in ('inactive', 'failed') or state.get('MainPID') != '0' for state in after.values()):
            raise RuntimeError('Fleet writers did not stop; backup was not taken.')
        yield
    finally:
        # Also restore after a partially failed stop, copy error or handled signal.
        control.restore(running)


def capture(data, stage):
    """Caller must hold the stopped-writer boundary for the entire capture."""
    if not (data/'fleet.sqlite').is_file():
        raise ValueError('Existing Fleet database is required; no bootstrap is performed.')
    with _writer_locks(data):
        names = _inventory(data)
        stats = {name: (data/name).stat() for name in names}
        target = stage/'data'
        target.mkdir(mode=0o700)
        with _connect(data/'fleet.sqlite') as source:
            with sqlite3.connect(target/'fleet.sqlite') as restored:
                source.backup(restored)
        (target/'fleet.sqlite').chmod(0o600)
        for name in names:
            if name == 'fleet.sqlite':
                continue
            path = target/name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(data/name, path)
            path.chmod(0o600)
        if _inventory(data) != names or any((data/name).stat().st_mtime_ns != stats[name].st_mtime_ns or
                                           (data/name).stat().st_size != stats[name].st_size for name in names):
            raise ValueError('Fleet data changed during the stopped-writer snapshot; no archive published.')
        with _connect(target/'fleet.sqlite') as c:
            if c.execute('pragma integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup SQLite integrity check failed.')
            tables = _tables(c)
        manifest = dict(version=1,created_at=dt.datetime.now(dt.timezone.utc).isoformat(),tables=tables,
                        files={name: dict(bytes=(target/name).stat().st_size,sha256=_hash(target/name)) for name in names})
        (stage/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        (stage/'manifest.json').chmod(0o600)
        return manifest


def verify_archive(archive, scratch_parent):
    """Restore only to an ephemeral private copy, verify each hash and all tables."""
    with tempfile.TemporaryDirectory(prefix='.fleet-restore-', dir=scratch_parent) as temp:
        root = Path(temp)
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            if len({m.name for m in members}) != len(members) or any(not m.isfile() for m in members):
                raise ValueError('Invalid backup archive members.')
            manifest = json.load(tar.extractfile('manifest.json'))
            expected = {'manifest.json', *('data/'+name for name in manifest['files'])}
            if {m.name for m in members} != expected:
                raise ValueError('Backup archive inventory does not match manifest.')
            for m in members:
                path = PurePosixPath(m.name)
                if path.is_absolute() or '..' in path.parts or not path.parts:
                    raise ValueError('Invalid backup archive path.')
                destination = root/Path(*path.parts)
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with destination.open('xb') as output:
                    shutil.copyfileobj(tar.extractfile(m), output)
                destination.chmod(0o600)
        for name, facts in manifest['files'].items():
            path = root/'data'/name
            if path.stat().st_size != facts['bytes'] or _hash(path) != facts['sha256']:
                raise ValueError('Backup restored file checksum failed.')
        with _connect(root/'data/fleet.sqlite') as c:
            if c.execute('pragma integrity_check').fetchone()[0] != 'ok' or _tables(c) != manifest['tables']:
                raise ValueError('Backup restored database verification failed.')
        return manifest


def full_backup(data, destination, *, writers_stopped=False, systemd=None):
    data = _private_directory(data); destination = _private_directory(destination)
    if data == destination or data in destination.parents:
        raise ValueError('Backup destination must be outside the Fleet data directory.')
    if not writers_stopped and systemd is None:
        raise ValueError('Stop writers explicitly or use the Fleet systemd quiesce mode.')
    with (destination/'.backup.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another Fleet backup is running.') from None
        with tempfile.TemporaryDirectory(prefix='.fleet-stage-', dir=destination) as staging:
            stage = Path(staging)
            if systemd is not None:
                with stopped_services(systemd):manifest = capture(data, stage)
            else:manifest = capture(data, stage)
            # Writers are already restored. Compression and verification read stage only.
            temporary = stage/'archive.tar.gz'
            with tarfile.open(temporary, 'w:gz') as tar:
                tar.add(stage/'manifest.json', arcname='manifest.json')
                for name in manifest['files']:
                    tar.add(stage/'data'/name, arcname='data/'+name, recursive=False)
            temporary.chmod(0o600)
            verified = verify_archive(temporary, destination)
            name = 'fleet-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.tar.gz'
            path = destination/name
            with temporary.open('rb') as stream:os.fsync(stream.fileno())
            os.link(temporary,path)  # Exclusive publish; never overwrite an older backup.
            directory = os.open(destination, os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
            return dict(path=str(path),files=len(verified['files']),tables=len(verified['tables']),sha256=_hash(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True)
    parser.add_argument('--destination', required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--writers-stopped', action='store_true')
    modes.add_argument('--quiesce-systemd', action='store_true')
    args=parser.parse_args()
    def interrupted(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    try:
        result=full_backup(args.data,args.destination,writers_stopped=args.writers_stopped,
                           systemd=Systemd() if args.quiesce_systemd else None)
    except (Exception,KeyboardInterrupt):
        print('Fleet backup failed. Previous backups and source data were preserved; inspect Fleet service status.')
        return 1
    print('Verified Fleet backup: '+result['path'])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
