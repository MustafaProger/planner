"""Read-only worker liveness; does not import the web app or expose provider data."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path


def read_worker_health(data_dir, *, max_age=45, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    path = Path(data_dir)/'refresh-heartbeat.json'
    result = {'healthy': False, 'reason': 'Обновление сервера ещё не запущено.',
              'heartbeat_at': None, 'age_seconds': None, 'running': False}
    try:
        state = json.loads(path.read_text())
        stamp = dt.datetime.fromisoformat(state['at'])
        if stamp.tzinfo is None:
            raise ValueError()
        age = (now-stamp).total_seconds()
        result.update(heartbeat_at=state['at'], age_seconds=round(age, 1),
                      running=bool(state.get('jobs')))
        if age < -5 or age > max_age:
            result['reason'] = 'Сервер перестал подтверждать работу обновления.'
            return result
        if state.get('status') != 'running':
            result['reason'] = 'Обновление сервера остановлено.'
            return result
        jobs = state.get('jobs', {})
        if not isinstance(jobs, dict):
            raise ValueError()
        for job in jobs.values():
            deadline = dt.datetime.fromisoformat(job['deadline_at'])
            if deadline.tzinfo is None:
                raise ValueError()
            if now > deadline:
                result['reason'] = 'Один из процессов обновления превысил допустимое время.'
                return result
        result.update(healthy=True, reason='Обновление сервера работает.')
        return result
    except FileNotFoundError:
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result['reason'] = 'Не удалось проверить состояние обновления сервера.'
        return result


def main():
    parser = argparse.ArgumentParser(description='Check local background-worker liveness without exposing account data.')
    parser.add_argument('--data', default=os.environ.get('FLEET_DATA'))
    args = parser.parse_args()
    if not args.data:
        parser.error('Specify --data or FLEET_DATA.')
    result = read_worker_health(args.data)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['healthy'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
