"""Account capabilities. Administrative permissions remain reserved for managers."""

RULES = {
    'plans.write': ('Рабочие записи', 'Создавать и изменять назначения', False),
    'plans.delete': ('Рабочие записи', 'Удалять назначения', False),
    'statuses.write': ('Рабочие записи', 'Устанавливать и заменять статусы календаря', False),
    'statuses.delete': ('Рабочие записи', 'Удалять статусы календаря', False),
    'trips.write': ('Рабочие записи', 'Создавать и изменять ручные заявки', False),
    'trips.delete': ('Рабочие записи', 'Удалять ручные заявки', False),
    'trips.classify': ('Рабочие записи', 'Изменять категорию заявок ТрансТрейда', True),
    'reviews.write': ('Рабочие записи', 'Сохранять решения по отклонениям', False),
    'catalog.write': ('Администрирование', 'Изменять справочники и тарифы', True),
    'settings.write': ('Администрирование', 'Изменять настройки и нормы расхода', True),
    'connections.run': ('Администрирование', 'Проверять подключения и обновлять данные', True),
    'coverage.write': ('Администрирование', 'Подтверждать полноту данных', True),
    'expenses.write': ('Администрирование', 'Изменять расходы', True),
    'fuel.read': ('Топливные карты', 'Просматривать операции и привязки карт', True),
    'fuel.write': ('Топливные карты', 'Изменять привязки карт к авто и водителям', True),
}


def role_default(role, key):
    return role == 'admin' or (role == 'logist' and not RULES[key][2])


def allowed(account, key):
    role = account['role']
    if RULES[key][2] and role != 'admin':
        return False
    overrides = account.get('permissions', {})
    if key == 'fuel.write' and not allowed(account, 'fuel.read'):
        return False
    return overrides.get(key, role_default(role, key))


def effective(account):
    return {key: allowed(account, key) for key in RULES}


def validate_overrides(role, value):
    if not isinstance(value, dict) or any(key not in RULES or type(flag) is not bool for key, flag in value.items()):
        raise ValueError('Проверьте полномочия пользователя')
    if role != 'admin' and any(flag and RULES[key][2] for key, flag in value.items()):
        raise ValueError('Эти полномочия доступны только руководителю')
    return {key: flag for key, flag in value.items() if flag != role_default(role, key)}


def describe():
    return [
        dict(key=key, group=group, label=label, manager_only=manager_only,
             defaults={role: role_default(role, key) for role in ('admin', 'logist', 'viewer')})
        for key, (group, label, manager_only) in RULES.items()
    ]
