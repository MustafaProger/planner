import React, { useEffect, useState } from "react";

const categories = ["Рейс", "Удержание", "Доплата", "Погрузка", "Сервис", "Корректировка"];
const catalogs = { vehicles: "Автомобили", drivers: "Водители", routes: "Маршруты", companies: "Компании", clients: "Клиенты", carriers: "Исполнители", transport_types: "Типы транспорта", payment_methods: "Способы оплаты", reasons: "Причины статусов" };
const today = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Moscow" });
const active = (p, kind) => (p.directories[kind] || []).filter(r => !r.archived && !r.merged_into && !r.placeholder);
function Field({ label, name, value, type = "text", required = false, ...props }) {
  return <label>{label}<input aria-label={label} name={name} type={type} defaultValue={value ?? ""} required={required} {...props} /></label>;
}
function Choice({ label, name, value, items, required = false, ...props }) {
  return <label>{label}<select aria-label={label} name={name} defaultValue={value || ""} required={required} {...props}><option value="">Выберите</option>{items.map(r => <option key={r.id ?? r} value={r.id ?? r}>{r.name ?? r}</option>)}</select></label>;
}
function Note({ value }) { return <label>Комментарий<textarea name="note" defaultValue={value || ""} maxLength={1000} /></label>; }

// Use the application's request/session helper and the same table and drawer primitives.
export function createRecordEditors({ api, hasPermission, Section, DataTable, Drawer }) {
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
        {editable && <button className="record-action" disabled={busy}>{label}</button>}
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
        <label>Источник<select value={selection.source} onChange={e => change("source", e.target.value)}><option value="trips">Заявки</option><option value="plans">Назначения</option></select></label>
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
    return <Section title={title} action={editable && <button className="record-action" onClick={() => setEditor({})}>Добавить</button>}>
      <DataTable title={title} rows={p[kind] || []} columns={[...fields.map(([key, label]) => ({ key, label })), { key: "note", label: "Комментарий" }, ...(editable ? [{ key: "actions", label: "Действия", render: row => <button className="text-link" onClick={() => setEditor({ row })}>Изменить</button> }] : [])]} />
      {editor && <Drawer title={title} size="compact" onClose={() => setEditor(null)}><ExtraEditor kind={kind} row={editor.row} p={p} period={period} onSaved={async () => { await refresh(); setEditor(null); }} /></Drawer>}
    </Section>;
  }
  function CatalogForm({ p, kind, row, onSaved }) {
    const r = row || {};
    return <Form onSubmit={async body => {
      const flags = Object.fromEntries(["archived", "partner", "inactive_route"].map(k => [k, body[k] === "on"]));
      await api("catalog/" + kind + (row ? "/" + row.id : ""), { method: row ? "PUT" : "POST", body: JSON.stringify({ ...r, ...body, ...flags, aliases: body.aliases.split("\n").map(s => s.trim()).filter(Boolean) }) }); await onSaved();
    }}>
      <Field label="Название" name="name" value={r.name} maxLength={200} required />
      <label>Другие названия, по одному в строке<textarea name="aliases" defaultValue={(r.aliases || []).join("\n")} /></label>
      {kind === "vehicles" && <><Choice label="Тип ресурса" name="resource_type" value={r.resource_type || "vehicle"} items={[{ id: "vehicle", name: "Автомобиль" }, { id: "partner", name: "Партнёр" }, { id: "service", name: "Сервис" }, { id: "placeholder", name: "Не определён" }]} required /><Field label="Марка" name="brand" value={r.brand} /><Choice label="Тип транспорта" name="transport_type_id" value={r.transport_type_id} items={active(p, "transport_types")} /></>}
      {["vehicles", "drivers"].includes(kind) && <><Choice label="Компания" name="company" value={r.company} items={active(p, "companies").map(c => ({ id: c.name, name: c.name }))} /><Choice label="Исполнитель" name="carrier_id" value={r.carrier_id} items={active(p, "carriers")} /></>}
      {kind === "drivers" && <label><input type="checkbox" name="partner" defaultChecked={r.partner} />Водитель партнёра</label>}
      {kind === "routes" && <><Field label="Группа маршрутов" name="group" value={r.group} /><label><input type="checkbox" name="inactive_route" defaultChecked={r.inactive_route} />Маршрут не выполняется</label></>}
      <label><input type="checkbox" name="archived" defaultChecked={r.archived} />В архиве</label>
    </Form>;
  }
  function CatalogManager({ p, user, refresh }) {
    const [kind, setKind] = useState("routes"), [editor, setEditor] = useState(null);
    if (!hasPermission(user, "catalog.write")) return null;
    return <Section title="Редактор справочников и тарифов" action={<button className="record-action" onClick={() => setEditor({})}>Добавить запись</button>}>
      <label>Справочник<select value={kind} onChange={e => setKind(e.target.value)}>{Object.entries(catalogs).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
      <DataTable title={catalogs[kind]} rows={(p.directories[kind] || []).filter(r => !r.merged_into)} columns={[{ key: "name", label: "Название" }, { key: "archived", label: "Состояние", render: r => r.archived ? "В архиве" : "Действует" }, { key: "actions", label: "Действия", render: row => <button className="text-link" onClick={() => setEditor({ row })}>Изменить</button> }]} />
      {kind === "routes" && <><button className="record-action" onClick={() => setEditor({ tariff: true })}>Добавить тариф с даты</button><DataTable title="История тарифов" rows={p.tariffs || []} columns={[{ key: "route_id", label: "Маршрут", render: r => p.directories.routes.find(x => x.id === r.route_id)?.name || "—" }, { key: "effective_from", label: "С даты" }, { key: "revenue", label: "Выручка, ₽" }, { key: "payout", label: "Водителю, ₽" }, { key: "partner_payout", label: "Партнёру, ₽" }, { key: "km", label: "Км" }]} /></>}
      {editor && <Drawer title={editor.tariff ? "Новый тариф" : catalogs[kind]} size="compact" onClose={() => setEditor(null)}>
        {editor.tariff ? <Form onSubmit={async body => { await api("tariffs", { method: "POST", body: JSON.stringify(body) }); await refresh(); setEditor(null); }}>
          <p>Исторические тарифы сохраняются. Новый тариф применяется с выбранной даты.</p>
          <Choice label="Маршрут" name="route_id" items={active(p, "routes")} required />
          <Field label="Действует с" name="effective_from" type="date" value={today()} required />
          {[["revenue", "Выручка, ₽"], ["payout", "Водителю, ₽"], ["partner_payout", "Партнёру, ₽"], ["km", "Пробег, км"], ["hours", "Часы"], ["rate", "Ставка водителя"], ["partner_rate", "Ставка партнёра"]].map(([name, label]) => <Field key={name} label={label} name={name} type="number" min="0" step="any" value={0} required />)}
        </Form> : <CatalogForm p={p} kind={kind} row={editor.row} onSaved={async () => { await refresh(); setEditor(null); }} />}
      </Drawer>}
    </Section>;
  }
  return { TripEditor, ExtraRecords, CatalogManager };
}
