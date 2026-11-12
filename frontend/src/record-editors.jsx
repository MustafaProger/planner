import React, { useEffect, useState } from "react";

const categories = ["Рейс", "Удержание", "Доплата", "Погрузка", "Сервис", "Корректировка"];
const catalogs = { vehicles: "Автомобили", drivers: "Водители", routes: "Маршруты", companies: "Компании", clients: "Клиенты", carriers: "Исполнители", transport_types: "Типы транспорта", payment_methods: "Способы оплаты", reasons: "Причины статусов" };
const catalogGroups = [
  ["fleet", "Автомобили и водители", ["vehicles", "drivers", "ownership"]],
  ["routes", "Маршруты", ["routes", "tariffs"]],
  ["organizations", "Организации", ["companies", "clients", "carriers"]],
  ["other", "Прочее", ["transport_types", "payment_methods", "reasons"]],
];
const catalogLabels = { ...catalogs, ownership: "Принадлежность", tariffs: "Тарифы" };
const today = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Moscow" });
const active = (p, kind) => (p.directories[kind] || []).filter(r => !r.archived && !r.merged_into && !r.placeholder);
function Field({ label, name, value, type = "text", required = false, ...props }) {
  return <label>{label}<input aria-label={label} name={name} type={type} defaultValue={value ?? ""} required={required} {...props} /></label>;
}
function Note({ value }) { return <label>Комментарий<textarea aria-label="Комментарий" name="note" defaultValue={value || ""} maxLength={1000} /></label>; }

// Use the application's request/session helper and the same table and drawer primitives.
export function createRecordEditors({ api, hasPermission, Section, DataTable, Drawer, SelectMenu, SlidingTabs, Button, Plus }) {
  function Choice({ label, name, value, items, required = false }) {
    return <label>{label}<SelectMenu ariaLabel={label} name={name} defaultValue={value || ""} required={required}
      options={[...(!required ? [{ value: "", label: "Не указано" }] : []), ...items.map(r => ({ value: r.id ?? r, label: r.name ?? r }))]} /></label>;
  }

  function Form({ children, onSubmit, onDelete, editable = true, label = "Сохранить" }) {
    const [busy, setBusy] = useState(false), [error, setError] = useState("");
    async function run(action) {
      if (busy) return;
      setBusy(true); setError("");
      try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); }
    }
    return <form className="form record-form" onSubmit={event => {
      event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget));
      if (editable) run(() => onSubmit(body));
    }}>
      <fieldset className="plan-fields" disabled={busy || !editable}>{children}</fieldset>
      {error && <p role="alert" className="error">{error}</p>}
      <div className="form-actions">
        {onDelete && <button type="button" className="record-delete" disabled={busy} onClick={() => {
          if (window.confirm("Удалить эту запись? Действие сохранится в журнале.")) run(onDelete);
        }}>Удалить</button>}
        {editable && (
          <Button type="submit" variant="primary" disabled={busy}>
            <span>{label}</span>
          </Button>
        )}
      </div>
    </form>;
  }
  function TripEditor({ p, row, user, onSaved }) {
    const [record, setRecord] = useState(row ? null : {}), [error, setError] = useState("");
    useEffect(() => {
      if (!row) return;
      let current = true;
      api("records/" + encodeURIComponent(row.record_id || row.id)).then(r => { if (current) setRecord(r); }).catch(e => { if (current) setError(e.message); });
      return () => { current = false; };
    }, [row]);
    if (error) return <p role="alert">{error}</p>;
    if (!record) return <p role="status">Загрузка заявки…</p>;
    const manual = !row || record.origin === "manual";
    const inScope = user.role === "admin" || !row || user.vehicles.includes(record.vehicle);
    const editable = inScope && hasPermission(user, manual ? "trips.write" : "trips.classify");
    const ref = (kind, field, label) => <Choice label={label} name={field + "_id"} value={record[field + "_id"]} items={active(p, kind).filter(r => kind !== "vehicles" || user.role === "admin" || user.vehicles.includes(r.name))} />;
    return <Form editable={editable} onSubmit={async body => {
      await api(row ? "records/" + encodeURIComponent(record.record_id) : "manual/trips", {
        method: row ? "PUT" : "POST", body: JSON.stringify({ ...body, date: body.start?.slice(0, 10), revision: record.revision }),
      }); await onSaved();
    }} onDelete={row && manual && inScope && hasPermission(user, "trips.delete") ? async () => {
      await api("manual/" + encodeURIComponent(record.record_id), { method: "DELETE", body: JSON.stringify({ revision: record.revision }) }); await onSaved();
    } : undefined}>
      {!manual && <p>Исходная заявка {record.id}. Здесь меняется только категория.</p>}
      <Choice label="Категория" name="category" value={record.category || "Рейс"} items={categories} required />
      {manual && <>
        <Field label="Номер заявки" name="id" value={record.id} required maxLength={100} />
        <Field label="Начало" name="start" type="datetime-local" value={record.start?.slice(0, 16) || today() + "T09:00"} required />
        <Field label="Окончание" name="end" type="datetime-local" value={record.end?.slice(0, 16) || today() + "T10:00"} required />
        {ref("vehicles", "vehicle", "Автомобиль")}{ref("drivers", "driver", "Водитель")}{ref("clients", "client", "Клиент")}
        {ref("carriers", "carrier", "Исполнитель")}{ref("transport_types", "type", "Тип транспорта")}
        {ref("payment_methods", "payment", "Оплата клиента")}{ref("payment_methods", "payout_method", "Оплата водителя")}
        <Field label="Выручка, ₽" name="revenue" type="number" step="any" value={record.revenue ?? 0} required />
        <Field label="Выплата, ₽" name="payout" type="number" step="any" value={record.payout ?? 0} required />
        <Field label="Пробег, км" name="km" type="number" min="0" step="any" value={record.km ?? 0} required />
        <Note value={record.note} />
      </>}
    </Form>;
  }
  function ExtraEditor({ kind, row, p, period, onSaved }) {
    const r = row || {}, [preview, setPreview] = useState(null), [previewError, setPreviewError] = useState(""), [previewBusy, setPreviewBusy] = useState(false);
    const coverage = kind === "coverage", binding = kind === "card_bindings";
    const [selection, setSelection] = useState({ source: r.source || "trips", start: r.start || period?.[0] || today(), end: r.end || period?.[1] || today() });
    function change(key, value) { setSelection(s => ({ ...s, [key]: value })); setPreview(null); setPreviewError(""); }
    return <Form label={coverage ? "Подтвердить полноту" : "Сохранить"} onSubmit={async body => {
      if (coverage && !preview) throw new Error("Сначала просмотрите итоги выбранного периода.");
      await api("workspace/" + kind + (row ? "/" + r.id : ""), { method: row ? "PUT" : "POST", body: JSON.stringify({ ...body, revision: r.revision, ...(coverage ? { ...selection, complete: true, checked_fingerprint: preview.checked_fingerprint, fingerprint_algorithm: preview.algorithm } : {}) }) });
      await onSaved();
    }} onDelete={row ? async () => { await api("workspace/" + kind + "/" + r.id, { method: "DELETE", body: JSON.stringify({ revision: r.revision }) }); await onSaved(); } : undefined}>
      {coverage ? <>
        <label>Источник<SelectMenu ariaLabel="Источник" value={selection.source} onChange={e => change("source", e.target.value)} options={[{ value: "trips", label: "Заявки" }, { value: "plans", label: "Назначения" }]} /></label>
        <label>С<input type="date" required value={selection.start} onChange={e => change("start", e.target.value)} /></label>
        <label>По<input type="date" required value={selection.end} onChange={e => change("end", e.target.value)} /></label>
        <button type="button" disabled={previewBusy} onClick={async () => {
          setPreview(null); setPreviewError(""); setPreviewBusy(true);
          try { setPreview(await api("workspace/coverage/preview?" + new URLSearchParams(selection))); } catch (e) { setPreviewError(e.message); } finally { setPreviewBusy(false); }
        }}>Просмотреть период</button>
        {previewError && <p role="alert">{previewError}</p>}
        {preview && <div role="status"><p>Записей: {preview.record_count}. Требуют проверки: {preview.unresolved_count}. Исключено: {preview.excluded_count}.</p><p>Выручка: {preview.summary.revenue ?? "—"} ₽. Выплаты: {preview.summary.payout ?? "—"} ₽.</p><p>Подтверждение относится ко всем автомобилям выбранного источника.</p></div>}
      </> : <>
        <Choice label="Автомобиль" name="vehicle_id" value={r.vehicle_id} items={active(p, "vehicles").filter(v => v.resource_type === "vehicle")} required />
        {binding ? <>
          <Choice label="Поставщик" name="provider" value={r.provider || "rosneft"} items={[{ id: "rosneft", name: "Роснефть" }, { id: "neftm", name: "Нефтьмагистраль" }]} required />
          <Field label="Номер карты" name="card" value={r.card} maxLength={100} required />
          <Field label="С" name="start" type="date" value={r.start || today()} required />
          <Field label="По" name="end" type="date" value={r.end || today()} required />
        </> : <>
          <Field label="Дата" name="date" type="date" value={r.date || today()} required />
          <Field label="Вид расхода" name="category" value={r.category} required />
          <Field label="Сумма, ₽" name="amount" type="number" min="0" step="any" value={r.amount ?? 0} required />
        </>}
      </>}
      <Note value={r.note} />
    </Form>;
  }
  function ExtraRecords({ kind, p, user, period, refresh }) {
    const [editor, setEditor] = useState(null);
    const permission = { coverage: "coverage.write", expenses: "expenses.write", card_bindings: "fuel.write" }[kind];
    const canRead = kind !== "card_bindings" || hasPermission(user, "fuel.read");
    if (!canRead || (kind !== "card_bindings" && !hasPermission(user, permission))) return null;
    const editable = hasPermission(user, permission);
    const title = { coverage: "Полнота данных", expenses: "Расходы", card_bindings: "Привязки карт к автомобилям" }[kind];
    const fields = kind === "coverage" ? [["source", "Источник"], ["start", "С"], ["end", "По"], ["state", "Состояние"]] : kind === "expenses" ? [["date", "Дата"], ["vehicle", "Автомобиль"], ["category", "Вид расхода"], ["amount", "Сумма, ₽"]] : [["provider", "Поставщик"], ["card", "Карта"], ["vehicle", "Автомобиль"], ["start", "С"], ["end", "По"]];
    return <Section title={title} action={editable && <div><Button type="button" size="medium" variant="primary" icon={<Plus size={16} />} onClick={() => setEditor({})}>Добавить</Button></div>}>
      <DataTable title={title} rows={p[kind] || []} columns={[...fields.map(([key, label]) => ({ key, label, ...(["source", "provider"].includes(key) ? { render: r => ({ trips: "Заявки", plans: "Назначения", rosneft: "Роснефть", neftm: "Нефтьмагистраль" })[r[key]] || r[key] } : {}) })), { key: "note", label: "Комментарий" }, ...(editable ? [{ key: "actions", label: "Действия", render: row => <button className="text-link" onClick={() => setEditor({ row })}>Изменить</button> }] : [])]} />
      {editor && <Drawer title={title} size="compact" onClose={() => setEditor(null)}>
        {(closeDrawer) => <ExtraEditor kind={kind} row={editor.row} p={p} period={period}
          onSaved={async () => { await refresh(); closeDrawer(); }} />}
      </Drawer>}
    </Section>;
  }
  function CatalogForm({ p, kind, row, onSaved }) {
    const r = row || {};
    return <Form onSubmit={async body => {
      const flags = Object.fromEntries(["archived", "partner", "inactive_route"].map(k => [k, body[k] === "on"]));
      await api("catalog/" + kind + (row ? "/" + row.id : ""), { method: row ? "PUT" : "POST", body: JSON.stringify({ ...r, ...body, ...flags, aliases: body.aliases.split("\n").map(s => s.trim()).filter(Boolean) }) }); await onSaved();
    }}>
      <Field label="Название" name="name" value={r.name} maxLength={200} required />
      <label>Другие названия, по одному в строке<textarea aria-label="Другие названия, по одному в строке" name="aliases" defaultValue={(r.aliases || []).join("\n")} /></label>
      {kind === "vehicles" && <><Choice label="Тип ресурса" name="resource_type" value={r.resource_type || "vehicle"} items={[{ id: "vehicle", name: "Автомобиль" }, { id: "partner", name: "Партнёр" }, { id: "service", name: "Сервис" }, { id: "placeholder", name: "Не определён" }]} required /><Field label="Марка" name="brand" value={r.brand} /><Choice label="Тип транспорта" name="transport_type_id" value={r.transport_type_id} items={active(p, "transport_types")} /></>}
      {["vehicles", "drivers"].includes(kind) && <><Choice label="Компания" name="company" value={r.company} items={active(p, "companies").map(c => ({ id: c.name, name: c.name }))} /><Choice label="Исполнитель" name="carrier_id" value={r.carrier_id} items={active(p, "carriers")} /></>}
      {kind === "drivers" && <label><input type="checkbox" name="partner" defaultChecked={r.partner} />Водитель партнёра</label>}
      {kind === "routes" && <><Field label="Группа маршрутов" name="group" value={r.group} /><label><input type="checkbox" name="inactive_route" defaultChecked={r.inactive_route} />Маршрут не выполняется</label></>}
      <label><input type="checkbox" name="archived" defaultChecked={r.archived} />В архиве</label>
    </Form>;
  }
  function CatalogManager({ p, user, refresh, ownership, onChoose }) {
    const [group, setGroup] = useState("fleet"), [kind, setKind] = useState("vehicles"), [editor, setEditor] = useState(null);
    const editable = hasPermission(user, "catalog.write");
    const kinds = catalogGroups.find(([id]) => id === group)[2];
    const fleetRows = kind === "vehicles" ? p.vehicles : kind === "drivers" ? p.drivers : null;
    const records = (p.directories[kind] || []).filter(r => !r.merged_into);
    const ids = new Set(records.map(r => r.name));
    const subjects = kind === "vehicles" ? p.vehicleMap : p.driverMap;
    const rows = fleetRows
      ? editable
        ? [...records.map(r => ({ ...subjects.get(r.name), ...r, carrier: subjects.get(r.name)?.carrier ?? r.carrier })), ...fleetRows.filter(r => !ids.has(r.name))]
        : fleetRows
      : records.filter(r => editable || !r.archived);
    const columns = [
      { key: "name", label: kind === "vehicles" ? "Автомобиль" : kind === "drivers" ? "Водитель" : "Название",
        render: r => fleetRows && subjects.has(r.name)
          ? <button className="text-link" type="button" onClick={() => onChoose(kind, r.name)}>{r.name}</button>
          : r.name },
      ...(fleetRows ? [{ key: "carrier", label: "Исполнитель" }] : []),
      ...(kind === "vehicles" ? [{ key: "brand", label: "Марка" }, { key: "transport_type", label: "Тип транспорта" }] : []),
      ...(kind === "routes" ? [{ key: "group", label: "Группа маршрутов" }] : []),
      { key: "state", label: "Состояние" },
      ...(editable ? [{ key: "actions", label: "Действия", sortable: false, align: "end",
        render: row => row.id && <button type="button" className="text-link" aria-label={`Изменить: ${row.name}`} onClick={() => setEditor({ row: records.find(r => r.id === row.id) })}>Изменить</button> }] : []),
    ];
    const add = (label) => editable && <Button type="button" size="medium" variant="primary" icon={<Plus size={16} />}
      onClick={() => setEditor({ tariff: kind === "tariffs" })}>{label}</Button>;
    const routes = new Map((p.directories.routes || []).map(r => [r.id, r.name]));
    return <>
      <SlidingTabs label="Группы справочников" className="catalog-tabs" items={catalogGroups}
        value={group} onChange={id => {
          if (id === group) return;
          setGroup(id); setKind(catalogGroups.find(([key]) => key === id)[2][0]);
        }} />
      <div className="segments catalog-subtabs" role="group" aria-label={catalogGroups.find(([id]) => id === group)[1]}>
        {kinds.map(id => <button type="button" key={id} className={id === kind ? "active" : ""}
          aria-pressed={id === kind} onClick={() => setKind(id)}>{id === "routes" ? "Список маршрутов" : catalogLabels[id]}</button>)}
      </div>
      {kind === "ownership" ? ownership : kind === "tariffs" ? (
        <Section title="История тарифов" subtitle="Тариф маршрута действует с указанной даты. Предыдущие тарифы сохраняются.">
          <DataTable key="tariffs" title="История тарифов" className="catalog-table" action={add("Добавить тариф")}
            rows={(p.tariffs || []).map(r => ({ ...r, route: routes.get(r.route_id) }))} columns={[
              { key: "route", label: "Маршрут" }, { key: "effective_from", label: "Действует с" },
              { key: "revenue", label: "Выручка, ₽" }, { key: "payout", label: "Водителю, ₽" },
              { key: "partner_payout", label: "Партнёру, ₽" }, { key: "km", label: "Плановый пробег, км" },
            ]} />
        </Section>
      ) : (
        <Section title={catalogLabels[kind]}>
          <DataTable key={kind} title={catalogLabels[kind]} className="catalog-table" action={add("Добавить запись")}
            rows={rows.map(r => ({ ...r, state: r.archived ? "В архиве" : r.inactive_route ? "Не выполняется" : !r.id && fleetRows ? "Из заявок" : "Действует" }))}
            columns={columns} />
        </Section>
      )}
      {editor && <Drawer title={editor.tariff ? "Новый тариф" : catalogs[kind]} size="compact" onClose={() => setEditor(null)}>
        {(closeDrawer) => editor.tariff ? <Form onSubmit={async body => { await api("tariffs", { method: "POST", body: JSON.stringify(body) }); await refresh(); closeDrawer(); }}>
          <p>Исторические тарифы сохраняются. Новый тариф применяется с выбранной даты.</p>
          <Choice label="Маршрут" name="route_id" items={active(p, "routes")} required />
          <Field label="Действует с" name="effective_from" type="date" value={today()} required />
          {[["revenue", "Выручка, ₽"], ["payout", "Водителю, ₽"], ["partner_payout", "Партнёру, ₽"], ["km", "Пробег, км"], ["hours", "Часы"], ["rate", "Ставка водителя"], ["partner_rate", "Ставка партнёра"]].map(([name, label]) => <Field key={name} label={label} name={name} type="number" min="0" step="any" value={0} required />)}
        </Form> : <CatalogForm p={p} kind={kind} row={editor.row} onSaved={async () => { await refresh(); closeDrawer(); }} />}
      </Drawer>}
    </>;
  }
  return { TripEditor, ExtraRecords, CatalogManager };
}
