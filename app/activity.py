"""Build audit diffs from persisted values within the business transaction."""
import json

INTERNAL_FIELDS = {
    'revision', 'record_id', 'delete_token', 'related_ids', 'legacy_snapshot',
    'user_edited', 'created_by', 'category_override', 'original_category',
    'checked_fingerprint', 'fingerprint_algorithm', 'confirmed_by', 'confirmed_at',
}


def changes(before, after, *, fields=None, subject=None):
    before = before or {}
    after = after or {}
    keys = fields if fields is not None else dict.fromkeys([*before, *after])
    return [
        dict(field=key, before=before.get(key), after=after.get(key), subject=subject)
        for key in keys
        if key not in INTERNAL_FIELDS and before.get(key) != after.get(key)
    ]


def row_body(connection, table, ident):
    # Callers select the table from the schema or a fixed allowlist.
    if ident is None:
        return None
    row = connection.execute(f'select body from {table} where id=?', (ident,)).fetchone()
    return json.loads(row['body']) if row else None


def record_subject(kind, row):
    if kind == 'statuses':
        return f"{row['date']} · {row['entity']}"
    if kind == 'plans':
        return f"{row['date']} · {row.get('vehicle') or row.get('route')}"
    return f"Заявка № {row.get('id')}"


def describe_record(kind, before, after):
    row = after or before
    if kind == 'statuses':
        fields = ('date', 'entity', 'reason', 'note')
    elif kind == 'plans':
        fields = ('date', 'vehicle', 'driver', 'route', 'state', 'slot', 'note',
                  'revenue', 'payout', 'km', 'hours', 'tariff_id')
    else:
        fields = ('category',) if row.get('origin') != 'manual' else (
            'id', 'date', 'start', 'end', 'vehicle', 'driver', 'client', 'carrier',
            'type', 'payment', 'payout_method', 'category', 'revenue', 'payout', 'km', 'hours', 'note',
        )
    return changes(before, after, fields=fields, subject=record_subject(kind, row))
