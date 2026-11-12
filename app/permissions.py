"""Account capabilities with role defaults and per-user overrides."""

# Each rule lists its group, label and whether logisticians get it by default.
RULES = {
    'plans.write': ('Рабочие записи', 'Создавать и изменять назначения', True),
    'plans.delete': ('Рабочие записи', 'Удалять назначения', True),
    'statuses.write': ('Рабочие записи', 'Устанавливать и заменять статусы календаря', True),
    'statuses.delete': ('Рабочие записи', 'Удалять статусы календаря', True),
    'trips.write': ('Рабочие записи', 'Создавать и изменять ручные заявки', True),
    'trips.delete': ('Рабочие записи', 'Удалять ручные заявки', True),
    'trips.classify': ('Рабочие записи', 'Изменять категорию заявок ТрансТрейда', False),
    'reviews.write': ('Рабочие записи', 'Сохранять решения по отклонениям', True),
    'catalog.write': ('Администрирование', 'Изменять справочники и тарифы', False),
    'settings.write': ('Администрирование', 'Изменять настройки и нормы расхода', False),
    'connections.run': ('Администрирование', 'Проверять подключения и обновлять данные', False),
    'coverage.write': ('Администрирование', 'Подтверждать полноту данных', False),
    'expenses.write': ('Администрирование', 'Изменять расходы', False),
    'fuel.read': ('Топливные карты', 'Просматривать операции и привязки карт', False),
    'fuel.write': ('Топливные карты', 'Изменять привязки карт к авто и водителям', False),
}


def role_default(role, key):
    return role == 'admin' or (role == 'logist' and RULES[key][2])


def allowed(account, key):
    overrides = account.get('permissions', {})
    if key == 'fuel.write' and not allowed(account, 'fuel.read'):
        return False
    return overrides.get(key, role_default(account['role'], key))


def effective(account):
    return {key: allowed(account, key) for key in RULES}


def validate_overrides(value):
    if not isinstance(value, dict) or any(key not in RULES or type(flag) is not bool for key, flag in value.items()):
        raise ValueError('Проверьте полномочия пользователя')
    return value


def describe():
    return [
        dict(key=key, group=group, label=label,
             defaults={role: role_default(role, key) for role in ('admin', 'logist', 'viewer')})
        for key, (group, label, _) in RULES.items()
    ]
