"""Independent incident observer; can report a stopped worker while the host lives."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

from app import alerts, autosync
from app.health import read_worker_health


def observe_once(data_dir, *, at=None, deliver=True):
    folder = Path(data_dir)
    at = at or dt.datetime.now(dt.timezone.utc)
    try:
        status = autosync.public_status(folder, expected=True)
    except Exception:
        # Never echo malformed file values, exception details or upstream bodies.
        status = None
    if status is None:
        heartbeat = read_worker_health(folder, now=at)
        status = {'scheduler_expected': True, 'server_scheduler': False,
                  'heartbeat_at': heartbeat.get('heartbeat_at'),
                  'started_at': at.isoformat(), 'sources': {},
                  'message': 'Состояние фонового обновления недоступно.'}
    # observe() persists first_seen. Fresh one-shot processes do not reset grace.
    return alerts.observe(folder, status, at=at, deliver=deliver)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default=os.environ.get('FLEET_DATA'))
    parser.add_argument('--no-delivery', action='store_true', help='Record incidents without sending external messages.')
    args = parser.parse_args()
    if not args.data:
        parser.error('Specify --data or FLEET_DATA.')
    try:
        result = observe_once(args.data, deliver=not args.no_delivery)
    except Exception:
        print('Incident observer could not access its state; check data permissions and storage.')
        return 1
    delivery = result.get('delivery', {})
    print(json.dumps({'active_incidents': len(result.get('incidents', [])),
                      'delivery_configured': delivery.get('configured', False),
                      'pending_notifications': delivery.get('pending', 0),
                      'storage_ok': not bool(result.get('storage_error'))}))
    return 1 if result.get('storage_error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
