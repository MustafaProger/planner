// Pure projections: no provider requests, no mutation of source records.
export const UNKNOWN = "Не указано";
export const STATUS_COLORS = {
  Работа: "#31856c",
  Выходной: "#689ac8",
  Больничный: "#b99350",
  "Ремонт / сервис": "#d58a58",
  "Без заявки": "#b2a47b",
  "Без водителя": "#a28eac",
  "Не заполнено": "#c85d5d",
  "Несколько статусов": "#b57736",
  "Другая работа": "#97a6ad",
};
export const REVIEW_STATES = [
  "Не проверено",
  "В работе",
  "Обосновано",
  "Нарушение",
  "Исправлено",
];
export const emptyFilters = () => ({
  carriers: [],
  vehicles: [],
  drivers: [],
  types: [],
  clients: [],
  statuses: [],
  ownership: [],
});
export const num = (v) =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
export const sum = (rows, key) =>
  rows.length && rows.every((r) => num(r[key]) !== null)
    ? rows.reduce((n, r) => n + r[key], 0)
    : null;
export const knownSum = (rows, key) =>
  rows.some((r) => num(r[key]) !== null)
    ? rows.reduce((n, r) => n + (num(r[key]) ?? 0), 0)
    : null;
export const ratio = (a, b) =>
  num(a) !== null && num(b) !== null && b !== 0 ? a / b : null;
export const percent = (a, b) =>
  ratio(a, b) === null ? null : ratio(a, b) * 100;
export const delta = (actual, base) =>
  num(actual) !== null && num(base) !== null
    ? { value: actual - base, percent: percent(actual - base, base) }
    : { value: null, percent: null };
export function validDay(s) {
  return (
    typeof s === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(s) &&
    !Number.isNaN(Date.parse(s)) &&
    new Date(s).toISOString().slice(0, 10) === s
  );
}
export const addDays = (day, n) =>
  new Date(Date.parse(day + "T12:00:00Z") + n * 86400000)
    .toISOString()
    .slice(0, 10);
export function daysBetween(a, b) {
  if (!validDay(a) || !validDay(b) || a > b) return [];
  const result = [];
  for (let d = a; d <= b && result.length < 731; d = addDays(d, 1))
    result.push(d);
  return result;
}
export function periodFor(day, kind) {
  const d = new Date(day + "T12:00:00Z"),
    y = d.getUTCFullYear(),
    m = d.getUTCMonth(),
    iso = (v) => v.toISOString().slice(0, 10);
  if (kind === "day") return [day, day];
  if (kind === "week") {
    const a = addDays(day, -((d.getUTCDay() + 6) % 7));
    return [a, addDays(a, 6)];
  }
  if (kind === "year") return [`${y}-01-01`, `${y}-12-31`];
  if (kind === "quarter") {
    const first = Math.floor(m / 3) * 3;
    return [
      iso(new Date(Date.UTC(y, first, 1))),
      iso(new Date(Date.UTC(y, first + 3, 0))),
    ];
  }
  return [
    iso(new Date(Date.UTC(y, m, 1))),
    iso(new Date(Date.UTC(y, m + 1, 0))),
  ];
}
export function previousPeriod(from, to) {
  for (const k of ["year", "quarter", "month", "week"]) {
    const [a, b] = periodFor(from, k);
    if (a === from && b === to) return periodFor(addDays(from, -1), k);
  }
  const n = daysBetween(from, to).length;
  return [addDays(from, -n), addDays(from, -1)];
}
export const selected = (values, value) =>
  !values?.length || values.includes(value || UNKNOWN);
export function category(r) {
  const t = (r.type || "").toLowerCase(),
    c = r.category || "Рейс";
  if (/удерж|штраф/.test(t) || c === "Удержание") return "Удержания";
  if (/преми/.test(t)) return "Премии";
  if (/прр|погруз|разгруз/.test(t) || c === "Погрузка") return "ПРР";
  if (/доплат/.test(t) || c === "Доплата") return "Доплаты";
  if (/доп.*работ/.test(t)) return "Дополнительные работы";
  if (/сервис|услуг|водител/.test(t)) return "Прочие начисления";
  if (c !== "Рейс") return c;
  return "Вождение";
}
export const isTrip = (r) =>
  !r.cancelled &&
  (r.category ?? "Рейс") === "Рейс" &&
  category(r) === "Вождение";
export const statusName = (v) =>
  ({
    Сервис: "Ремонт / сервис",
    Ремонт: "Ремонт / сервис",
    "Нет заявки": "Без заявки",
    БезВодителя: "Без водителя",
  })[v] ||
  v ||
  "Не заполнено";
export function tripSpan(r) {
  const a = validDay(r.start?.slice(0, 10)) ? r.start.slice(0, 10) : r.date;
  const e = r.end?.slice(0, 10);
  return [a, validDay(e) && e >= a ? e : a];
}
const overlaps = (r, a, b) => {
  const [s, e] = tripSpan(r);
  return validDay(s) && s <= b && e >= a;
};
const active = (r) => !r.archived && !r.merged_into;
export const ownership = (company) =>
  !company || company === UNKNOWN
    ? "Не установлено"
    : /чартер|charter/i.test(company)
      ? "Собственный парк"
      : "Привлечённые";
export function prepare(d) {
  const cats = d.directories || {},
    vs = (cats.vehicles || []).filter(
      (r) => active(r) && (!r.resource_type || r.resource_type === "vehicle"),
    ),
    ds = (cats.drivers || []).filter((r) => active(r) && !r.placeholder);
  const vehicleMap = new Map(vs.map((r) => [r.name, r])),
    driverMap = new Map(ds.map((r) => [r.name, r]));
  const seen = new Set(),
    duplicates = [],
    trips = [];
  for (const r of d.trips || []) {
    const id = String(r.record_id || r.id);
    if (seen.has(id)) {
      duplicates.push(r);
      continue;
    }
    seen.add(id);
    trips.push(r);
    if (
      r.vehicle &&
      !vehicleMap.has(r.vehicle) &&
      !(cats.vehicles || []).some(
        (x) =>
          x.name === r.vehicle &&
          x.resource_type &&
          x.resource_type !== "vehicle",
      )
    )
      vehicleMap.set(r.vehicle, { name: r.vehicle, unregistered: true });
    if (r.driver && !driverMap.has(r.driver))
      driverMap.set(r.driver, { name: r.driver, unregistered: true });
  }
  const companyKey = (name) =>
    String(name || "")
      .toLowerCase()
      .replace(/[^а-яёa-z0-9 ]/g, " ")
      .split(/\s+/)
      .filter(Boolean)
      .sort()
      .join(" ");
  const resolveCarrier = (r) => {
    const explicit =
      r.carrier ||
      (cats.carriers || []).find((c) => c.id === r.carrier_id)?.name;
    if (explicit) return explicit;
    const same = (cats.carriers || []).filter(
      (c) => r.company && companyKey(c.name) === companyKey(r.company),
    );
    return same.length === 1 ? same[0].name : r.company || UNKNOWN;
  };
  const vehicles = [...vehicleMap.values()].map((v) => ({
    ...v,
    carrier: resolveCarrier(v),
    ownership: ownership(resolveCarrier(v)),
    transport_type:
      v.transport_type ||
      (cats.transport_types || []).find((t) => t.id === v.transport_type_id)
        ?.name ||
      UNKNOWN,
  }));
  const drivers = [...driverMap.values()].map((v) => ({
    ...v,
    carrier: resolveCarrier(v),
    ownership: ownership(resolveCarrier(v)),
  }));
  return {
    ...d,
    trips,
    vehicles,
    drivers,
    vehicleMap: new Map(vehicles.map((v) => [v.name, v])),
    driverMap: new Map(drivers.map((v) => [v.name, v])),
    duplicates,
  };
}
export function matches(r, f, p) {
  const v = p.vehicleMap.get(r.vehicle);
  return (
    selected(f.vehicles, r.vehicle) &&
    selected(f.drivers, r.driver) &&
    selected(f.clients, r.client) &&
    selected(f.types, r.type) &&
    selected(f.carriers, r.carrier) &&
    selected(f.ownership, v?.ownership || "Не установлено")
  );
}
export function available(p, f) {
  const matchingTypes = f.types.length
    ? new Set(p.trips.filter((r) => f.types.includes(r.type) && isTrip(r)).map((r) => r.vehicle))
    : null;
  const vehicles = p.vehicles.filter(
    (v) =>
      selected(f.carriers, v.carrier) &&
      selected(f.ownership, v.ownership) &&
      (!matchingTypes ||
        f.types.includes(v.transport_type) ||
        matchingTypes.has(v.name)),
  );
  const drivers = p.drivers.filter(
    (v) =>
      selected(f.carriers, v.carrier) && selected(f.ownership, v.ownership),
  );
  return { vehicles, drivers };
}
export function calendarRows(p, f, from, to, mode = "vehicle") {
  const options = available(p, f),
    names = (mode === "vehicle" ? options.vehicles : options.drivers).filter(
      (v) => selected(mode === "vehicle" ? f.vehicles : f.drivers, v.name),
    );
  const spans = p.trips.filter((r) => isTrip(r) && overlaps(r, from, to)),
    selectedTrips = spans.filter((r) => matches(r, f, p));
  const index = new Map(),
    allIndex = new Map(),
    statusIndex = new Map();
  function push(map, k, r) {
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(r);
  }
  for (const r of spans) {
    const [a, b] = tripSpan(r);
    for (const day of daysBetween(a < from ? from : a, b > to ? to : b))
      push(allIndex, `${r[mode]}|${day}`, r);
  }
  for (const r of selectedTrips) {
    const [a, b] = tripSpan(r);
    for (const day of daysBetween(a < from ? from : a, b > to ? to : b))
      push(index, `${r[mode]}|${day}`, r);
  }
  for (const r of p.statuses || [])
    if (r.kind === mode && r.date >= from && r.date <= to)
      push(statusIndex, `${r.entity}|${r.date}`, r);
  const dates = daysBetween(from, to);
  return names
    .flatMap((v) =>
      dates.map((date) => {
        const k = `${v.name}|${date}`,
          trips = index.get(k) || [],
          other = allIndex.get(k) || [],
          events = statusIndex.get(k) || [],
          reasons = [...new Set(events.map((s) => statusName(s.reason)))];
        const status = trips.length
          ? "Работа"
          : other.length
            ? "Другая работа"
            : reasons.length === 1
              ? reasons[0]
              : reasons.length > 1
                ? "Несколько статусов"
                : "Не заполнено";
        return {
          date,
          name: v.name,
          vehicle:
            mode === "vehicle"
              ? v.name
              : [...new Set(trips.map((t) => t.vehicle))].join(", "),
          driver:
            mode === "driver"
              ? v.name
              : [...new Set(trips.map((t) => t.driver).filter(Boolean))].join(
                  ", ",
                ),
          carrier: v.carrier,
          status,
          events,
          trips,
          other,
        };
      }),
    )
    .filter((r) => selected(f.statuses, r.status));
}
export function financial(rows) {
  const work = rows.filter(isTrip),
    revenue = sum(rows, "revenue"),
    payout = sum(rows, "payout"),
    km = sum(work, "km"),
    hours = sum(work, "hours"),
    balance = revenue !== null && payout !== null ? revenue - payout : null;
  return {
    records: rows.length,
    trips: work.length,
    revenue,
    payout,
    balance,
    margin: percent(balance, revenue),
    payout_percent: percent(payout, revenue),
    km,
    hours,
    average: ratio(sum(work, "revenue"), work.length),
    rub_km: ratio(revenue, km),
    rub_hour: ratio(revenue, hours),
    driver_payout: sum(rows, "driver_payout"),
  };
}
export const extraEventCount = (day) =>
  day.trips.length || day.other.length
    ? day.events.length
    : Math.max(0, day.events.length - 1);

export function postingRows(p, f, from, to, days) {
  const posting = p.trips.filter(
    (r) =>
      !r.cancelled &&
      validDay(r.date) &&
      r.date >= from &&
      r.date <= to &&
      matches(r, f, p),
  );
  if (!f.statuses.length) return posting;
  const statusDates = new Set((days ?? calendarRows(p, f, from, to)).map((d) => `${d.vehicle}|${d.date}`));
  return posting.filter((r) => statusDates.has(`${r.vehicle}|${r.date}`));
}

export function analyze(
  p,
  f,
  from,
  to,
  settings = { movement_threshold: 10 },
  fuel = [],
) {
  const days = calendarRows(p, f, from, to);
  const rows = postingRows(p, f, from, to, days);
  const carNames = new Set(
    available(p, f)
      .vehicles.filter((v) => selected(f.vehicles, v.name))
      .map((v) => v.name),
  );
  const sat = p.satellite.filter(
    (r) => r.date >= from && r.date <= to && carNames.has(r.vehicle),
  );
  // Daily telemetry belongs to a vehicle, never implicitly to its driver/client.
  const satelliteScoped = !!(
    f.drivers.length ||
    f.clients.length ||
    f.statuses.length
  );
  const daySat = new Map();
  for (const r of sat) {
    const key = `${r.vehicle}|${r.date}`;
    if (!daySat.has(key)) daySat.set(key, []);
    daySat.get(key).push(r);
  }
  const movementDays =
    satelliteScoped ||
    ![...daySat.values()].some((rs) => sum(rs, "km") !== null)
      ? null
      : [...daySat.values()].filter(
          (rs) =>
            sum(rs, "km") !== null &&
            sum(rs, "km") >= settings.movement_threshold,
        ).length;
  const stats = financial(rows);
  const byStatus = new Map();
  for (const day of days) {
    if (!byStatus.has(day.status)) byStatus.set(day.status, []);
    byStatus.get(day.status).push(day);
  }
  const workDays = byStatus.get("Работа")?.length ?? 0;
  const statusNames = new Set([...Object.keys(STATUS_COLORS), ...byStatus.keys()]);
  const statuses = [...statusNames].filter((name) => byStatus.has(name)).map((name) => ({
    name,
    color: STATUS_COLORS[name] || "#82939d",
    value: byStatus.get(name).length,
    dates: byStatus.get(name),
  }));
  const ops = fuel.filter(
    (r) =>
      r.date >= from &&
      r.date <= to &&
      selected(f.vehicles, r.vehicle) &&
      (!f.carriers.length ||
        selected(f.carriers, p.vehicleMap.get(r.vehicle)?.carrier)) &&
      (!f.ownership.length ||
        selected(f.ownership, p.vehicleMap.get(r.vehicle)?.ownership)) &&
      (!f.types.length || carNames.has(r.vehicle)),
  );
  return {
    ...stats,
    filters: f,
    rows,
    days,
    statuses,
    satellite: sat,
    satelliteScoped,
    daySat,
    movementDays,
    sat_km: satelliteScoped ? null : knownSum(sat, "km"),
    sat_coverage: daySat.size,
    workDays,
    load: percent(workDays, days.length),
    revenue_day: ratio(stats.revenue, workDays),
    events: days.reduce((n, d) => n + extraEventCount(d), 0),
    fuel: ops,
    from,
    to,
  };
}
export function groups(p, a, key) {
  const buckets = new Map();
  const vehicleDays = new Map();
  for (const r of a.rows) {
    const name = r[key] || UNKNOWN;
    if (!buckets.has(name)) buckets.set(name, []);
    buckets.get(name).push(r);
  }
  // The calendar includes incoming overnight trips whose financial posting is in another period.
  for (const day of a.days) {
    if (key === "vehicle") {
      if (!buckets.has(day.vehicle)) buckets.set(day.vehicle, []);
      if (!vehicleDays.has(day.vehicle)) vehicleDays.set(day.vehicle, []);
      vehicleDays.get(day.vehicle).push(day);
    }
    for (const r of day.trips) {
      const name = r[key] || UNKNOWN;
      if (!buckets.has(name)) buckets.set(name, []);
    }
  }
  return [...buckets]
    .map(([name, rows]) => {
      const ownDays =
        key === "driver"
          ? calendarRows(
              p,
              { ...a.filters, drivers: [name] },
              a.from,
              a.to,
              "driver",
            )
          : key === "vehicle"
            ? vehicleDays.get(name) ?? []
            : a.days.filter((d) => d.trips.some((r) => (r[key] || UNKNOWN) === name));
      const dates = new Set();
      for (const day of ownDays)
        if (day.trips.some((r) => (r[key] || UNKNOWN) === name))
          dates.add(key === "driver" ? day.date : `${day.vehicle}|${day.date}`);
      const v = p.vehicleMap.get(name);
      return {
        name,
        ...financial(rows),
        rows,
        days: dates.size,
        load: percent(
          ownDays.filter((d) => d.status === "Работа").length,
          ownDays.length,
        ),
        carrier: v?.carrier,
        transport_type: v?.transport_type,
        ownership: v?.ownership,
      };
    })
    .sort((x, y) => (y.revenue ?? -Infinity) - (x.revenue ?? -Infinity));
}
export function timeline(a, unit = "day") {
  const map = new Map();
  for (const r of a.rows) {
    const name = unit === "month" ? r.date.slice(0, 7) : r.date;
    if (!map.has(name)) map.set(name, []);
    map.get(name).push(r);
  }
  return [...map]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, rs]) => ({ name, ...financial(rs), rows: rs }));
}
export function deviations(p, a, settings, fuel = a.fuel) {
  const out = [];
  const push = (kind, day, detail, value = null) =>
    out.push({
      id: `${kind}|${day.vehicle}|${day.date}${day.ref ? "|" + day.ref : ""}`,
      kind,
      date: day.date,
      vehicle: day.vehicle,
      driver: day.driver,
      carrier: day.carrier,
      detail,
      value,
    });
  for (const d of a.days) {
    const readings = a.daySat.get(`${d.vehicle}|${d.date}`) || [],
      km = sum(readings, "km"),
      engine = sum(readings, "engine_hours");
    if (d.status === "Не заполнено")
      push(
        "Не заполненный день",
        d,
        "Нет заявки и вручную установленного статуса",
      );
    if (!a.satelliteScoped) {
      if (!d.other.length && km !== null && km >= settings.movement_threshold)
        push(
          "Движение без заявки",
          d,
          `${km.toFixed(1)} км за сутки; требуется проверить цель поездки`,
          km,
        );
      if (d.other.length && km !== null && km < settings.movement_threshold)
        push(
          "Заявка без движения",
          d,
          `${km.toFixed(1)} км; ниже порога ${settings.movement_threshold} км`,
          km,
        );
      if (d.other.length && km === null)
        push(
          "Нет спутниковых данных",
          d,
          "Отсутствие данных не означает отсутствие движения",
        );
      if (engine > 0 && km !== null && km < settings.movement_threshold)
        push(
          "Моточасы без движения",
          d,
          `${engine.toFixed(1)} моточасов; возможен холостой ход или ошибка зажигания`,
          engine,
        );
      // Only full-day, non-overlapping TT intervals can be compared to daily telemetry.
      const exact =
        d.other.length === 1 &&
        d.other[0].start?.endsWith("T00:00:00") &&
        d.other[0].end === `${addDays(d.date, 1)}T00:00:00`;
      const tt = sum(d.other, "km");
      if (exact && tt !== null && km !== null) {
        const diff = km - tt;
        if (
          diff > settings.excess_km &&
          (tt === 0 || percent(diff, tt) > settings.excess_percent)
        )
          push("Перепробег", d, `ТТ ${tt} км · ГЛОНАСС ${km} км`, diff);
      }
    }
  }
  const opDays = new Map();
  for (const r of fuel.filter((r) => r.liters > 0)) {
    const k = `${r.vehicle || r.provider + ":" + r.card}|${r.date}`;
    if (!opDays.has(k)) opDays.set(k, []);
    opDays.get(k).push(r);
  }
  const calendar = new Map();
  if (opDays.size)
    for (const day of a.days) {
      const key = `${day.vehicle}|${day.date}`;
      if (opDays.has(key) && !calendar.has(key)) calendar.set(key, day);
    }
  for (const rs of opDays.values()) {
    const r = rs[0],
      d = {
        date: r.date,
        vehicle: r.vehicle || UNKNOWN,
        carrier: p.vehicleMap.get(r.vehicle)?.carrier || UNKNOWN,
        ref: r.provider + ":" + r.card,
      };
    if (!r.vehicle)
      push(
        "Заправка без привязки",
        d,
        "Нет однозначной исторической связи карты с автомобилем",
      );
    if (rs.length > 1)
      push(
        "Повторные заправки за день",
        d,
        `${rs.length} операций. Точного времени недостаточно для оценки интервала.`,
        rs.length,
      );
    const cal = calendar.get(`${r.vehicle}|${r.date}`);
    if (cal && cal.status !== "Работа" && cal.status !== "Другая работа")
      push(
        "Заправка в день без работы",
        d,
        `Календарь: ${cal.status}. Требуется проверка.`,
      );
  }
  return out;
}
export function quality(p) {
  const q = [];
  for (const v of p.vehicles) {
    if (v.carrier === UNKNOWN)
      q.push({ name: v.name, kind: "Автомобиль без исполнителя" });
    if (v.transport_type === UNKNOWN)
      q.push({
        name: v.name,
        kind: "Тип автомобиля не установлен в справочнике",
      });
  }
  for (const v of p.drivers)
    if (v.carrier === UNKNOWN)
      q.push({ name: v.name, kind: "Водитель без исполнителя" });
  for (const r of p.trips) {
    if (!validDay(r.date))
      q.push({ name: r.id, kind: "Некорректная дата заявки" });
    if (r.end && (!validDay(r.end.slice(0, 10)) || r.end < r.start))
      q.push({ name: r.id, kind: "Некорректный интервал заявки" });
    if (isTrip(r) && (!r.vehicle || !r.driver))
      q.push({ name: r.id, kind: "Заявка без автомобиля или водителя" });
  }
  for (const r of p.duplicates)
    q.push({ name: r.id, kind: "Дублирующаяся запись" });
  return q;
}
export function swapResult(a, b) {
  const revenue =
    num(a.revenue) !== null && num(b.revenue) !== null
      ? a.revenue + b.revenue
      : null;
  const current =
    revenue !== null && num(a.payout) !== null && num(b.partner_payout) !== null
      ? revenue - a.payout - b.partner_payout
      : null;
  const alternative =
    revenue !== null && num(b.payout) !== null && num(a.partner_payout) !== null
      ? revenue - b.payout - a.partner_payout
      : null;
  return { revenue, current, alternative, ...delta(alternative, current) };
}
