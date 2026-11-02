#!/usr/bin/env python3
"""Create a private, consistent SQLite backup. Does not copy credentials or JSON history."""
import argparse
import os
import sqlite3
from pathlib import Path


def backup(data_dir, destination):
    source = Path(data_dir)/'fleet.sqlite'
    destination = Path(destination)
    if not source.is_file() or not destination.is_absolute():
        raise ValueError('Existing source database and absolute destination are required.')
    if not destination.parent.is_dir() or destination.parent.stat().st_mode & 0o077:
        raise ValueError('Create a private destination directory (0700) first.')
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True, timeout=30) as src:
            with sqlite3.connect(destination) as target:
                src.backup(target)
                if target.execute('pragma integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup integrity check failed.')
    except Exception:
        # Only remove the new destination owned by this attempt, never a prior backup.
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default=os.environ.get('FLEET_DATA'))
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    if not args.data:
        parser.error('Specify --data or FLEET_DATA.')
    try:
        backup(args.data, args.destination)
    except (ValueError, OSError, sqlite3.Error):
        print('Backup failed; check private paths, free space and database availability.')
        return 1
    print('SQLite backup verified. Provider JSON histories and credentials are not included.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
