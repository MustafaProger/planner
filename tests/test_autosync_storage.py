"""Storage-failure interleavings, using only an isolated temporary queue."""
import datetime as dt
import threading

from app import autosync, refresh


def test_job_save_failure_during_scheduler_recovery_is_not_cleared(tmp_path, monkeypatch):
    service = refresh.RefreshService(tmp_path, tmp_path/'unused.sqlite', lambda: {'vehicles': []})
    engine = autosync.Scheduler(service, 300)
    engine._load()
    task = engine.state['tasks']['transtrade:current']
    task.update(status='running', started_at=autosync.now().isoformat(),
                next_run_at=(autosync.now()+dt.timedelta(minutes=5)).isoformat())
    engine.storage_error = 'Earlier storage failure awaiting recovery.'
    prepared, finished = threading.Event(), threading.Event()
    scheduler_thread = threading.current_thread()

    class InterleavedGuard:
        """Let the waiting job finish before the scheduler resumes after unlock.

        This forces the formerly unsafe ordering deterministically: a job can
        record a new failed save immediately after recovery releases the lock.
        Clearing the error after that release would erase the newer failure.
        """
        def __init__(self):
            self.lock = threading.RLock()
            self.armed = False
            self.completed = False

        def __enter__(self):
            self.lock.acquire()
            return self

        def __exit__(self, *_):
            self.lock.release()
            if self.armed and threading.current_thread() is scheduler_thread:
                self.armed = False
                engine.stop_event.set()
                self.completed = finished.wait(3)

    guard = InterleavedGuard()
    engine.guard = guard
    monkeypatch.setattr(engine, '_load', lambda: None)
    monkeypatch.setattr(engine, '_beat', lambda: None)
    monkeypatch.setattr(engine, '_launch', lambda *_: None)
    engine.alert_due = float('inf')

    def current(_):
        prepared.set()
        return {'message': 'Synthetic completed provider read.'}

    def run_job():
        try:
            engine._job('transtrade', 'current')
        finally:
            finished.set()

    monkeypatch.setattr(engine, '_current', current)
    job = threading.Thread(target=run_job, daemon=True, name='synthetic-storage-failure')
    original_save = engine._save
    saves = []

    def save():
        if threading.current_thread() is job:
            raise OSError('Synthetic write failure; no provider or working data is used.')
        original_save()
        saves.append(1)
        if len(saves) == 2:
            # First save initializes the loop; the second repairs an older
            # failure while the new job is ready to record its own result.
            guard.armed = True
            job.start()
            assert prepared.wait(3)

    monkeypatch.setattr(engine, '_save', save)
    try:
        engine.run()
    finally:
        engine.stop_event.set()
        if job.ident is not None:
            job.join(3)

    assert guard.completed and not job.is_alive()
    assert engine.storage_error, 'A later job storage failure must survive recovery of an earlier failure.'
    assert task['status'] == 'success'
    assert autosync.read_state(tmp_path)['tasks']['transtrade:current']['status'] == 'running'
    assert not (tmp_path/'unused.sqlite').exists()
