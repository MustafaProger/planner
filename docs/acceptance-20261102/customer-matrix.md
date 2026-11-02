# Приемка требований заказчика — 2 ноября 2026

Подробные доказательства к [единому текущему итогу](../current-status.md). Проверка завершена в 14:34 МСК. Проверенная основа приложения: `677636891dcfc13109d0467f9b3448af3a709daa`. Python и интерфейс приложения в этом цикле не изменялись; хеши проверенных файлов записаны в [checks.json](checks.json) и [browser.json](browser.json). Изменения тестового окружения фиксируются отдельным последующим коммитом.

**В согласованном объеме механизмы прошли приемку.** Нового воспроизводимого дефекта расчетов, сохранности или интерфейса не обнаружено. Автоматический километраж ТТ отложен пользователем; реальные смены, привязки, расходы, причины и подтверждение полноты требуют фактов ответственного. Это не приемка полной реальной экономики и не подтверждение абсолютной полноты API.

## Полученные доказательства

- **P** — один свежий полный прогон `.venv/bin/python -m pytest -q`: **396 passed**, без пропусков, **7 проверок предоставленных книг** выполнены, 3 предупреждения openpyxl о неподдерживаемых расширениях при чтении. Время 9,123 с. До импорта сервера заданы временный `FLEET_DATA` и `FLEET_SCHEDULER=disabled`; мутации используют тестовые базы и поддельных поставщиков. [Результат и хеши](checks.json).
- **B** — новый Chromium 156.0.8078.4 / Playwright 1.64.1, **1440×1000 и 390×844**, 4,394 с. Временный сервер на случайном порту loopback, сгенерированные книги, отдельные admin/logist/viewer; SQLite и обычные HTTP API настоящие. Только GET `/api/refresh` подменен завершенным фиктивным обновлением для проверки сохранности формы. Реальные поставщики не настроены, их изменяющие endpoints заблокированы; внешние браузерные запросы запрещены. В обоих viewport — **0 page errors и 0 внешних запросов**. [Результат и хеши](browser.json), [сценарий](fixtures/browser.cjs), [временный сервер](fixtures/server.py).
- **J** — обычные JavaScript-регрессии и восстановленный браузерный sidebar-сценарий описаны в [отчете F02](sidebar.md). Эти проверки отделены от B: mocked sidebar сам по себе не аттестует живой Python backend.

B прошел настоящий вход, показал 3 200 ₽ выручки, 1 100 ₽ выплат, 4 записи, 2 рейса, 1 рабочий день и 31 час при неизвестном КМ. Проверил денежные средние, десять группировок, CSV и четыре исходные записи в детализации; отдельные ТТ↔спутник и план↔факт, шесть заголовков дельт; незавершенный ввод при событии обновления; сохранение независимых статусов автомобиля и водителя. На дате без заказов обе сущности получили 0 рейсов, 0 рабочих дней и 1 статусный день; деньги и часы прежние. Созданы планы на январь и февраль **2027** и второе назначение первого дня: 32 / 29 записей, 32 000 / 29 000 ₽; обе матрицы сохранили каждое назначение. Формы карт, расходов, полноты с preview и экран смен открыты; роли проверены через интерфейс и HTTP403. На экране смен нет горизонтального переполнения документа при обеих ширинах. Скриншоты входа desktop и экрана смен mobile дополнительно просмотрены визуально; они содержат только тестовые данные и остаются в `.local/customer-acceptance-20261102/`.

Воспроизведение B после установки Python-зависимостей в `.venv`:

```sh
npm ci
npm run browser:install
node docs/acceptance-20261102/fixtures/browser.cjs
```

Сценарий сам создает и удаляет временную БД, закрывает собственный browser и сервер, имеет общий предел 120 с и 7-секундные ожидания элементов. `ACCEPTANCE_PYTHON` позволяет явно выбрать Python, `ACCEPTANCE_OUTPUT` — каталог результатов. Результаты повторного запуска по умолчанию пишутся в `.local/`, датированный опубликованный JSON не перезаписывается автоматически.

## R01–R30: готовность и граница

«Проверено» означает проверенный механизм на P/B/J, а не заполненность рабочих данных. Имена тестов ниже принадлежат свежему набору P, если не обозначено иначе. Для эксплуатационного состояния VPS используется отдельный датированный снимок в текущем итоге; эта приемка не обращалась к production.

| ID и критерий | Результат / доказательство | Остаток или ограничение |
|---|---|---|
| R01 — заявки, мониторинг, план и простои в одном приложении | Проверено: B открывает общие отчеты, заявки/детали, обе сверки, план и календарь; P `test_page_navigation_and_unknown_paths` | Реальное наполнение частичное; повторный ручной ввод всех заявок не требуется |
| R02 — кнопка и автономное обновление подключенных источников | P [test_refresh.py](../../tests/test_refresh.py): `test_scheduler_starts_real_provider_job_without_browser`, `test_failure_isolated_and_previous_success_retained`, period/history/backoff; B сохраняет ввод при завершении обновления | P использует fake providers; текущий VPS/источники оцениваются отдельно; автоматический КМ отложен |
| R03 — источник, ID и история исправлений ТТ | P [test_transtrade_reconciliation.py](../../tests/test_transtrade_reconciliation.py): `test_full_scope_discovers_hidden_orders_preserves_excel_and_repeats`, `test_full_preserves_manual_deleted_and_category_override`, `test_disappeared_order_is_kept_even_if_direct_id_empty` | Локальная категория не выдается за правку в ТТ; отсутствие в выдаче не доказывает удаление |
| R04 — произвольный период и календарные разрезы | B выбирает день/неделю/месяц/квартал/год и создает планы 2027; P `test_period_moscow_and_provider_limit`, `test_filter_and_actual_days` | Суточный спутник и дата начала заявки имеют разную гранулярность, показанную в сверке |
| R05 — деньги, записи, рейсы и дни раздельно | B: 4 записи/2 рейса/1 день; P `test_means_distinguish_records_trips_and_total_money`, `test_non_trip_charges_do_not_inflate_work` | Спорную исходную категорию исправляет ответственный |
| R06 — машина, водитель, клиент, исполнитель, марка и принадлежность | P [test_reporting_gaps.py](../../tests/test_reporting_gaps.py): `test_groups_do_not_multiply_facts_or_guess_company`, `test_filter_details_and_export_rows_share_one_selection`; B разрезы и средние | Принадлежность из текущего справочника, исторические интервалы не восстановлены |
| R07 — независимые машина/водитель и сочетание | P `test_driver_changes_cars_with_disjoint_intervals`, `test_split_drivers_no_daily_prorating`, `test_driver_company_filter_does_not_attribute_vehicle_telemetry`; B группировка пары | Суточные показатели не делятся между водителями без достаточных интервалов |
| R08 — ТТ↔спутник с единицами и неизвестными значениями | B отдельная сверка, объяснение знака ТТ−спутник и пустых КМ; P `test_reconcile_missing_not_zero` | Реальный КМ ТТ отложен; моточасы не равны длительности смены |
| R09 — раскрытие отклонения до исходных записей | B детали строки со всеми 4 записями; J [test_navigation.cjs](../../tests/test_navigation.cjs): возврат/Forward/сохранение фильтров после drill-down | Нет измерений — нет заявления о нулевом отклонении |
| R10 — показатели эффективности водителей | P денежные/рейсовые средние в `test_means_distinguish_records_trips_and_total_money`; B группы и средние | Точный пробег и фактические смены требуют подтвержденных данных |
| R11 — выплаты, доплаты, удержания, сервис и ПРР | P `test_non_trip_charges_do_not_inflate_work`, `test_means_distinguish_records_trips_and_total_money`; B 4 вида исходных записей в деталях | Выплата исполнителю не переименована автоматически в зарплату штатного водителя |
| R12 — самостоятельный ручной статус автомобиля/водителя | B создает оба вида через форму; P `test_manual_idempotence_and_soft_delete`, `test_role_boundaries_and_assignment` | Реальные причины не заполняются догадкой |
| R13 — простой в статистике без фиктивного заказа | B сохраняет статусы без изменения 2 рейсов; P `test_unique_status_days_and_overlap` | Статусный день и работа могут сосуществовать |
| R14 — календарь работы и причин по двум сущностям | B проверяет появление причин и переключение строки машина/водитель; P уникальные дни/пересечения | Пустой день не объявляется доказанным простоем |
| R15 — справочники и устойчивые связи | P `test_seed_separates_brand_company`, `test_renames_references_and_companies`, `test_merge_keeps_status_provenance_and_delete` | Неоднозначные назначения требуют реальных решений |
| R16 — маршрутные условия и плановые деньги/КМ/часы | P `test_plan_weekdays_and_rate`, `test_tariff_effective_date_and_freeze`, 7 Excel checks; B новые плановые суммы | Итоговые ставки задаются явно; зарплата и партнерская выплата не суммируются произвольно |
| R17 — план на длинный период и несколько работ | B месяц 2027 плюс отдельная смена; P `test_plan_weekdays_and_rate` | Реальные неназначенные ресурсы не распределены автоматически |
| R18 — две матрицы плана без потери назначений | B 32/29 назначений в каждой матрице; J `route and vehicle matrices keep each assignment and its stable actions once` | Ограничений механизма в проверке не найдено |
| R19 — плановые рейсы, деньги, КМ, часы, доля выплат | P `test_plan_routes_and_totals`, `test_no_route_and_duplicate_not_counted`; B суммы нового месяца сходятся с записями | Спорные повторы и «нет маршрута» исключаются явно; реальная полнота отдельно |
| R20 — будущий план↔факт как отдельный отчет | B три группы показателей и все 6 дельт; P `test_six_comparison_deltas_and_metric_specific_reasons` | Дельта требует сопоставимых данных и подтвержденного периода; доступные исходные деньги видны |
| R21 — работа без будущего плана | P `test_nonoverlapping_period_no_delta_and_explicit_zero`, `test_empty_full_period_zeros_are_distinct`; B августовский факт без августовского плана | Непроверенное отсутствие плана не заменяется нулем |
| R22 — отчеты, графики, фильтры, детали и экспорт | B группы, CSV и детали; P фильтры/единая выборка; J `statistics presents filtered API rows consistently in table, details and CSV` | Не обещается произвольный набор новых отчетов |
| R23 — объяснимые средние и производные показатели | P `test_total_is_weighted_by_raw_records_and_missing_is_not_zero`, `test_card_binding_dates_overlap_expenses_and_no_guessed_allocation`; B средние и деньги без КМ | Результат известных затрат — не чистая прибыль; полнота затрат требует фактов |
| R24 — два топлива, возвраты и привязки по датам | P [test_rosneft.py](../../tests/test_rosneft.py), [test_neftm.py](../../tests/test_neftm.py), `test_fuel_history_refund_and_interval_replacement`, `test_card_binding_dates_overlap_expenses_and_no_guessed_allocation`; B готовая форма привязки | Фактическая история карт не возникает из имени держателя; актуальные источники см. эксплуатационный снимок |
| R25 — существующие роли и машины логиста | B admin/login, viewer без ввода, logist с вводом, оба без управления пользователями (403); P `test_role_boundaries_and_assignment`, CSRF и assignments | Проверена существующая матрица; новые права не придуманы |
| R26 — источник, единицы, пропуски и полнота | P [test_integrity_gaps.py](../../tests/test_integrity_gaps.py): fingerprint/create/edit/delete/no-op/stale preview; B preview полноты и объяснения null | Технический успех API не равен бизнес-полноте |
| R27 — датированный тариф, история сохраняется | P `test_tariff_effective_date_and_freeze`: суммы 1000/1000/2000 остаются после повторного импорта с тарифом 3000 | Применена принятая модель замороженных условий; история не пересчитывается молча |
| R28 — точное сопоставление маршрута и заявки | Честное агрегатное сравнение по машине/водителю/периоду проверено P/B | Надежный общий ключ/правило для построчного маршрута не установлен; новая функция не заявлена |
| R29 — работа и статус в один день, доля дня | P `test_unique_status_days_and_overlap`: один день, две причины, overlap; B отдельные статусы | Приоритет/оплата/доли дня не определены заказчиком, события сохранены без выдуманной формулы |
| R30 — налоги и полная себестоимость | P исходные суммы и известные затраты; B прежняя семантика показателей | Правила 1,05/1,22 и полной себестоимости не установлены; чистая прибыль не заявлена |

## A1–A10 и защитные регрессии

| Сценарий | Свежий результат и конкретное доказательство |
|---|---|
| A1 — два рейса и штраф в один день | P `test_means_distinguish_records_trips_and_total_money`: 3200 ₽/4 записи/2 рейса/1 день, средние 800/1500/1600; B те же деньги с 31 часом и неизвестным КМ |
| A2 — исправленный заказ без дубля и потери непереданных полей | P `test_full_scope_discovers_hidden_orders_preserves_excel_and_repeats`, `test_full_preserves_manual_deleted_and_category_override`, `test_real_sync_preserves_supplement_and_coverage_invalidation` |
| A3 — смена водителя/машины | P `test_driver_changes_cars_with_disjoint_intervals`, `test_split_drivers_no_daily_prorating`: целые измерения сохраняются, общий суточный остаток не делится по догадке |
| A4 — ночной интервал 27 часов | P `test_27_hours_and_conservation` дает 27 ч и сохранение всех КМ; B второй рейс 27 ч плюс первый 4 ч дает 31 ч, не 7 |
| A5 — простой без заказа и пересечение с работой | B независимые статусы автомобиля и водителя в календаре; P `test_unique_status_days_and_overlap` и idempotence/soft-delete |
| A6 — месяц плана и факт без плана | B 2027-01/02 + дополнительная смена, обе матрицы и суммы; P `test_nonoverlapping_period_no_delta_and_explicit_zero` |
| A7 — даты тарифа и исходные суммы | P `test_tariff_effective_date_and_freeze`, `test_plan_routes_and_totals`; исходные книги проверяются как контроль импорта, не как всеобщий DAX-эталон |
| A8 — пропуски спутника/КМ | P `test_reconcile_missing_not_zero`, `test_total_is_weighted_by_raw_records_and_missing_is_not_zero`; B km=null не скрывает деньги/часы и не превращается в нулевую дельту |
| A9 — фильтры, итоги, график, детали, CSV | P `test_filter_details_and_export_rows_share_one_selection`; J `statistics presents filtered API rows consistently in table, details and CSV`; B группы, средние, CSV/детали через браузер |
| A10 — повторное топливо, возврат и непривязанная карта | P `test_fuel_history_refund_and_interval_replacement`: 3 операции после повтора, возврат −10 л; `test_card_binding_dates_overlap_expenses_and_no_guessed_allocation`: одна непривязанная операция остается отдельно |
| G01 — переносимые исходные книги | P [test_importer_portable.py](../../tests/test_importer_portable.py) и все 7 Excel checks; B генерирует свои книги |
| G02 — актуальность подтвержденной полноты | P `test_preview_stale_or_missing_is_rejected`, `test_create_edit_delete_and_outside_period`, `test_tt_noop_then_money_cancel_date_change`, `test_excel_noop_change_and_category`, `test_merge_invalidates_identity_even_without_amount_change` |
| G03–G05 — разрезы, дельты и средние | P семь тестов [test_reporting_gaps.py](../../tests/test_reporting_gaps.py); B группы, средние, шесть колонок Δ, доступные деньги |
| G06 — stale DELETE не теряет чужие правки | P `test_two_connections_cannot_both_delete`, `test_status_merge_group_version_and_membership_atomic`, `test_http_conflict_csrf_and_preview`, `test_busy_writer_is_conflict_without_partial_delete`; J конфликт с явным перечитыванием UI |
| Формы при обновлении | B незавершенный текст и dialog сохраняются при новом last_finished_at, затем запись успешно сохранена; J [test_refresh_ui.cjs](../../tests/test_refresh_ui.cjs) также покрывает ввод во время fetch, failed submit, disclosure и scroll |

Не выполнялись мутации рабочей БД, повторная публикация, перезагрузка VPS, смена доступов, реальные уведомления и принудительное обновление поставщиков. B покрывает перечисленные экраны/сценарии в Chromium, а не все возможные браузеры и устройства. Отдельная реальная доставка предупреждения ожидает выбранного получателя; точность частичного дня телеметрии — подходящих измерений и подтвержденных смен.
