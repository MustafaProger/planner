"""Supervised background process. Provider outages do not count as process failure."""
import logging
import os
import signal
import socket
import threading
import time


LOG = logging.getLogger(__name__)


def notify(message, environ=None):
    """Minimal sd_notify client; never contacts a network service."""
    address = (os.environ if environ is None else environ).get('NOTIFY_SOCKET')
    if not address:
        return False
    if address.startswith('@'):
        address = '\0'+address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect(address)
            sock.sendall(message.encode('utf-8'))
        return True
    except OSError:
        return False


def supervise(service, stopped=None, *, poll_seconds=5, startup_grace=30,
              join_timeout=30, monotonic=time.monotonic, notifier=notify):
    """Exit on a dead scheduler or expired job deadline so systemd can restart it.

    runtime_health() reports local execution liveness only. A provider's network
    failure remains a retryable application incident and must not restart every
    other source. A hard process freeze is covered by systemd's watchdog.
    """
    stopped = stopped or threading.Event()
    started = monotonic()
    ready = False
    code = 0
    try:
        service.start_scheduler()
        while not stopped.is_set():
            try:
                health = service.runtime_health()
                healthy = health.get('healthy') is True
            except Exception:
                healthy = False
            if healthy:
                if not ready:
                    notifier('READY=1\nSTATUS=Background updates are running')
                    ready = True
                notifier('WATCHDOG=1')
            elif ready or monotonic()-started >= startup_grace:
                LOG.error('Background scheduler stopped or exceeded its execution deadline.')
                notifier('STATUS=Background scheduler requires restart')
                code = 1
                break
            if stopped.wait(poll_seconds):
                break
    except Exception:
        # Do not print exceptions: a future provider adapter could include secrets.
        LOG.error('Background worker could not run; saved data will be retried.')
        code = 1
    finally:
        notifier('STOPPING=1')
        try:
            service.stop(join_timeout=join_timeout)
        except Exception:
            LOG.error('Background worker did not finish its bounded shutdown.')
            code = 1
    return code


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    # Import only after signal handlers: importing worker for tests is side-effect free.
    from app import server
    try:
        server.init()
    except Exception:
        LOG.error('Worker initialization failed. Check deployment preflight and data permissions.')
        return 1
    return supervise(server.refresh_service, stopped)


if __name__ == '__main__':
    raise SystemExit(main())
