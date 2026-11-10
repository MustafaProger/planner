import sqlite3
from contextlib import closing

import pytest

from app import rosneft_drivers as assignments, workspace


def test_driver_assignments_follow_dates_and_manual_override(tmp_path, monkeypatch):
    path = tmp_path / 'fleet.sqlite'
    with closing(sqlite3.connect(path)) as c, c:
        c.row_factory = sqlite3.Row
        workspace.schema(c)
        first = workspace.save_catalog(c, 'drivers', {'name': 'Иванов Пётр Иванович'})
        second = workspace.save_catalog(c, 'drivers', {'name': 'Сидоров Иван Петрович'})

    cards = [
        {'Num': '001', 'Rem': 'Водитель: ИВАНОВ  Петр Иванович (грузовик)'},
        {'Num': '002', 'Rem': 'Иванов П. И.'},
        {'Num': '003', 'Rem': 'Иванов Пётр Иванович / Сидоров Иван Петрович'},
    ]
    monkeypatch.setattr(assignments, 'today', lambda: '2026-11-10')
    assignments.reconcile(path, {'cards': cards})
    assignments.reconcile(path, {'cards': cards})
    with closing(sqlite3.connect(path)) as c, c:
        history = assignments.timeline(c)
        assert set(history) == {'001'}
        assert len(history['001']) == 1
        assert history['001'][0]['driver_id'] == first
        body = dict(card='002', driver_id=second, start='2026-11-10', revision=None)
        assignments.assign(c, body, cards)
        with pytest.raises(workspace.ConflictError):
            assignments.assign(c, body, cards)

    monkeypatch.setattr(assignments, 'today', lambda: '2026-11-13')
    cards[0]['Rem'] = 'Сидоров Иван Петрович'
    cards[1]['Rem'] = 'Иванов Пётр Иванович'
    assignments.reconcile(path, {'cards': cards})
    with closing(sqlite3.connect(path)) as c:
        dates = [('001', '2026-11-10'), ('001', '2026-11-11'),
                 ('001', '2026-11-14'), ('002', '2026-11-14')]
        operations = [dict(provider='rosneft', operation='11', card=card, date=day)
                      for card, day in dates]
        assignments.label_operations(c, operations)
        assert [op.get('driver') for op in operations] == [
            None, 'Иванов Пётр Иванович', 'Сидоров Иван Петрович', 'Сидоров Иван Петрович',
        ]
