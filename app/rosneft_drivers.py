"""Date-based driver assignments, separate from vehicle and supplier data."""
import datetime as dt
import json
import re
import sqlite3
from collections import defaultdict
from contextlib import closing

from app.workspace import ConflictError, iso, today


def schema(c):
    c.execute("""
        CREATE TABLE IF NOT EXISTS rosneft_driver_assignments (
            id INTEGER PRIMARY KEY,
            card TEXT NOT NULL,
            start TEXT NOT NULL,
            driver_id TEXT,
            source TEXT NOT NULL CHECK(source IN ('auto', 'manual'))
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS rosneft_driver_card_start
        ON rosneft_driver_assignments(card, start, id)
    """)


def drivers(c):
    return {
        ident: json.loads(body)
        for ident, body in c.execute("SELECT id, body FROM catalog WHERE kind='drivers'")
    }


def selectable(driver):
    return not (driver.get('archived') or driver.get('placeholder'))


def timeline(c):
    rows = defaultdict(list)
    for row in c.execute("""
        SELECT id, card, start, driver_id, source
        FROM rosneft_driver_assignments ORDER BY start, id
    """):
        ident, card, start, driver, source = row
        rows[card].append(dict(id=ident, card=card, start=start, driver_id=driver, source=source))
    return rows


def words(value):
    return ' '.join(re.findall(r'[^\W_]+(?:-[^\W_]+)*', value.casefold().replace('ё', 'е')))


def reconcile(db_path, snapshot):
    """Called under the supplier sync lock only for a fresh successful response."""
    start = (dt.date.fromisoformat(today()) + dt.timedelta(days=1)).isoformat()
    with closing(sqlite3.connect(db_path, timeout=30)) as c, c:
        c.execute('BEGIN IMMEDIATE')
        schema(c)
        catalog = drivers(c)
        names = defaultdict(list)
        for ident, driver in catalog.items():
            name = words(driver['name'])
            if len(name.split()) == 3 and all(re.fullmatch(r'[а-я]{2,}(?:-[а-я]{2,})*', part) for part in name.split()):
                names[name].append(ident)
        cards = {row['Num']: row['Rem'] for row in snapshot['cards']}
        history = timeline(c)
        for card in cards.keys() | history.keys():
            previous = history[card][-1] if history[card] else None
            if previous and previous['source'] == 'manual':
                continue
            note = ' ' + words(cards.get(card, '')) + ' '
            candidates = [ident for name, ids in names.items() if f' {name} ' in note for ident in ids]
            match = candidates[0] if len(candidates) == 1 and selectable(catalog[candidates[0]]) else None
            if match != (previous['driver_id'] if previous else None):
                c.execute(
                    "INSERT INTO rosneft_driver_assignments(card, start, driver_id, source) VALUES (?, ?, ?, 'auto')",
                    (card, start, match),
                )


def assign(c, body, cards):
    if not isinstance(body, dict):
        raise ValueError('Укажите карту, водителя и дату.')
    card, driver = body.get('card'), body.get('driver_id')
    if not isinstance(card, str) or not any(row['Num'] == card for row in cards):
        raise ValueError('Выберите карту из списка Роснефти.')
    catalog = drivers(c)
    if not isinstance(driver, str) or driver not in catalog or not selectable(catalog[driver]):
        raise ValueError('Выберите действующего водителя из справочника.')
    start = iso(body.get('start'))
    rows = timeline(c)[card]
    last = rows[-1] if rows else None
    if body.get('revision') != (last['id'] if last else None):
        raise ConflictError('Назначение изменилось. Обновите список карт.')
    if last and start < last['start']:
        raise ValueError('Выберите дату не раньше последней привязки.')
    c.execute(
        "INSERT INTO rosneft_driver_assignments(card, start, driver_id, source) VALUES (?, ?, ?, 'manual')",
        (card, start, driver),
    )


def label_operations(c, operations):
    history = timeline(c)
    catalog = drivers(c)
    for op in operations:
        if op['provider'] != 'rosneft' or op['operation'] not in ('11', '24'):
            continue
        assignment = next((r for r in reversed(history[op['card']]) if r['start'] <= op['date']), None)
        if assignment:
            op['driver'] = catalog.get(assignment['driver_id'], {}).get('name', '')
