"""Cross-process locks for the web process and autonomous provider worker."""
import fcntl
import os
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path


@contextmanager
def file_lock(folder,name,timeout=0):
    with (Path(folder)/(name+'.lock')).open('a') as handle:
        os.chmod(handle.name,0o600)
        deadline=time.monotonic()+timeout
        while True:
            try:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:
                    raise ValueError('Источник уже обновляется; повторная загрузка будет выполнена позже.') from None
                time.sleep(.05)
        yield


def provider_lock(name):
    def decorate(fn):
        @wraps(fn)
        def wrapped(data_dir,*args,**kwargs):
            with file_lock(data_dir,name):
                return fn(data_dir,*args,**kwargs)
        return wrapped
    return decorate
