#!/usr/bin/env python3
"""Read-only deployment checks. Never creates users, copies keys or alters routing."""
import argparse
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path


PROVIDERS = {
    'transtrade': 'transtrade-credentials.json',
    'monitoring': 'monitoring-credentials.json',
    'rosneft': 'rosneft-credentials.json',
    'neftm': 'neftm-api.key',
}


def check(data_dir, *, required=tuple(PROVIDERS), platform=None):
    data_dir = Path(data_dir)
    platform = platform or sys.platform
    errors = []
    if not data_dir.is_absolute() or not data_dir.is_dir():
        return ['Data directory must be an existing absolute path; provision the approved data snapshot first.']
    if data_dir.is_symlink():
        errors.append('Data directory must not be a symlink.')
    if stat.S_IMODE(data_dir.stat().st_mode) & 0o077:
        errors.append('Data directory must be private (mode 0700).')
    if not os.access(data_dir, os.R_OK | os.W_OK | os.X_OK):
        errors.append('Service account cannot read and write the data directory.')
    for provider in required:
        if provider not in PROVIDERS:
            errors.append('Unknown required provider in FLEET_REQUIRED_PROVIDERS.')
    for name in ['fleet.sqlite', 'session.key', *[PROVIDERS[p] for p in required if p in PROVIDERS]]:
        path = data_dir/name
        if path.is_symlink() or not path.is_file():
            errors.append(f'Required private file is missing or is a symlink: {name}.')
            continue
        if not path.stat().st_size or not os.access(path, os.R_OK):
            errors.append(f'Required private file is empty or unreadable: {name}.')
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            errors.append(f'Private file must have mode 0600: {name}.')
    route = data_dir/'transtrade-network.json'
    if route.exists():
        try:
            setting = json.loads(route.read_text())
            if not isinstance(setting, dict):
                raise ValueError()
            if setting.get('interface') and platform != 'darwin':
                errors.append('TransTrade network configuration belongs to macOS. Review the target server route; do not copy the Mac interface setting.')
        except (OSError, ValueError):
            errors.append('Invalid TransTrade network configuration.')
    database = data_dir/'fleet.sqlite'
    if database.is_file() and not database.is_symlink():
        try:
            with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True, timeout=10) as connection:
                if connection.execute('pragma quick_check').fetchone()[0] != 'ok':
                    errors.append('SQLite integrity check failed.')
                for table, query in (
                    ('workspace_meta', "select 1 from workspace_meta where key='initialized'"),
                    ('users', 'select 1 from users limit 1'),
                    ('snapshot', 'select 1 from snapshot where id=1'),
                ):
                    if not connection.execute(query).fetchone():
                        errors.append(f'Existing application data is not provisioned: {table}.')
        except sqlite3.Error:
            errors.append('SQLite data is unavailable or incompatible; no initialization was attempted.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default=os.environ.get('FLEET_DATA'))
    parser.add_argument('--required-providers', default=os.environ.get('FLEET_REQUIRED_PROVIDERS', ','.join(PROVIDERS)))
    args = parser.parse_args()
    if not args.data:
        parser.error('Specify --data or FLEET_DATA.')
    required = tuple(part.strip() for part in args.required_providers.split(',') if part.strip())
    errors = check(args.data, required=required)
    for message in errors:
        print(message, file=sys.stderr)
    if not errors:
        print('Preflight passed: existing private data is available. Provider connectivity is checked by the worker after startup.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
