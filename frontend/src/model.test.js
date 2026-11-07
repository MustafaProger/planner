import test from "node:test";
import assert from "node:assert/strict";
import * as M from "./model.js";
const trip = (id, date, extra = {}) => ({
  id,
  date,
  start: date + "T08:00:00",
  end: date + "T16:00:00",
  category: "Рейс",
  vehicle: "А001АА77",
  driver: "Водитель А",
  carrier: "Чартер",
  client: "Клиент А",
  type: "1,5 тонны",
  revenue: 300,
  payout: 200,
  km: 100,
  hours: 8,
  ...extra,
});
function data(trips = [], extra = {}) {
  return M.prepare({
    trips,
    statuses: [],
    satellite: [],
    directories: {
      vehicles: [
        {
          id: "v1",
          name: "А001АА77",
          company: "Чартер",
          transport_type: "1,5 тонны",
        },
        {
          id: "v2",
          name: "А002АА77",
          company: "ИП Петров",
          transport_type: "5 тонн",
        },
      ],
      drivers: [{ id: "d1", name: "Водитель А", company: "Чартер" }],
    },
    ...extra,
  });
}
const f = () => ({ ...M.emptyFilters(), vehicles: ["А001АА77"] });
test("two trips share one working car-day; repair remains an additional event", () => {
  const p = data([trip("1", "2026-11-01"), trip("2", "2026-11-01")], {
    statuses: [
      {
        date: "2026-11-01",
        kind: "vehicle",
        entity: "А001АА77",
        reason: "Ремонт",
      },
    ],
  });
  const a = M.analyze(p, f(), "2026-11-01", "2026-11-02");
  assert.equal(a.trips, 2);
  assert.equal(a.workDays, 1);
  assert.equal(a.events, 1);
  assert.equal(a.load, 50);
  assert.equal(a.days[0].status, "Работа");
  assert.equal(a.days[1].status, "Не заполнено");
  assert.equal(
    a.statuses.reduce((n, s) => n + s.value, 0),
    2,
  );
});
test("overnight trip counts once, occupies both dates and keeps its full mileage", () => {
  const p = data([
    trip("1", "2026-10-31", { end: "2026-11-01T16:00:00", km: 450 }),
  ]);
  const oct = M.analyze(p, f(), "2026-10-31", "2026-10-31"),
    nov = M.analyze(p, f(), "2026-11-01", "2026-11-01");
  assert.equal(oct.trips, 1);
  assert.equal(nov.trips, 0);
  assert.equal(oct.workDays, 1);
  assert.equal(nov.workDays, 1);
  assert.equal(oct.km, 450);
  assert.equal(nov.km, null);
});
test("unknown amount is not zero; percentages have explicit TT base", () => {
  assert.equal(M.sum([{ km: null }, { km: 0 }], "km"), null);
  assert.equal(M.sum([{ km: 0 }], "km"), 0);
  assert.deepEqual(M.delta(200, 0), { value: 200, percent: null });
  assert.deepEqual(M.delta(230, 200), { value: 30, percent: 15 });
  assert.equal(M.delta(230, null).value, null);
});
test("financial result subtracts payout once even with a driver payout present", () => {
  const s = M.financial([trip("1", "2026-11-01", { driver_payout: 50 })]);
  assert.equal(s.balance, 100);
  assert.equal(s.payout_percent, (200 / 300) * 100);
  assert.equal(s.driver_payout, 50);
});
test("multi-selection unions across objects and intersects dimensions", () => {
  const p = data([
    trip("1", "2026-11-01"),
    trip("2", "2026-11-01", {
      vehicle: "А002АА77",
      carrier: "ИП Петров",
      type: "5 тонн",
    }),
  ]);
  let fs = {
    ...f(),
    vehicles: ["А001АА77", "А002АА77"],
    carriers: ["Чартер", "ИП Петров"],
  };
  assert.equal(M.analyze(p, fs, "2026-11-01", "2026-11-01").trips, 2);
  fs.clients = ["Другой"];
  assert.equal(M.analyze(p, fs, "2026-11-01", "2026-11-01").trips, 0);
  assert.ok(
    M.analyze(p, fs, "2026-11-01", "2026-11-01").days.every(
      (d) => d.status === "Другая работа",
    ),
  );
});
test("missing assignment never derives from an order carrier", () => {
  const p = data([trip("1", "2026-11-01")], {
    directories: { vehicles: [{ name: "А001АА77" }], drivers: [] },
  });
  assert.equal(p.vehicles[0].carrier, M.UNKNOWN);
  assert.equal(p.vehicles[0].ownership, "Не установлено");
});
test("pay categories are not real trips or vehicle classes", () => {
  const p = data([
    trip("1", "2026-11-01", { type: "ПРР" }),
    trip("2", "2026-11-01", { type: "Премия" }),
  ]);
  assert.equal(M.analyze(p, f(), "2026-11-01", "2026-11-01").trips, 0);
  assert.equal(M.category(p.trips[0]), "ПРР");
});
test("explicit no-order status differs from missing status", () => {
  const p = data([], {
    statuses: [
      {
        date: "2026-11-01",
        kind: "vehicle",
        entity: "А001АА77",
        reason: "Нет заявки",
      },
    ],
  });
  const a = M.analyze(p, f(), "2026-11-01", "2026-11-02");
  assert.deepEqual(
    a.days.map((d) => d.status),
    ["Без заявки", "Не заполнено"],
  );
});
test("movement threshold retains real mileage; missing telemetry is not no-movement", () => {
  const p = data([trip("1", "2026-11-01"), trip("2", "2026-11-02")], {
    satellite: [
      { vehicle: "А001АА77", date: "2026-11-01", km: 8, engine_hours: 4 },
    ],
  });
  const settings = {
      movement_threshold: 10,
      excess_km: 30,
      excess_percent: 10,
    },
    a = M.analyze(p, f(), "2026-11-01", "2026-11-02", settings);
  assert.equal(a.sat_km, 8);
  assert.equal(a.movementDays, 0);
  const issues = M.deviations(p, a, settings);
  assert.equal(
    issues.filter((i) => i.kind === "Заявка без движения").length,
    1,
  );
  assert.equal(
    issues.filter((i) => i.kind === "Нет спутниковых данных").length,
    1,
  );
  assert.equal(issues.filter((i) => i.kind === "Перепробег").length, 0);
});
test("driver workday is unique across two cars; satellite is not attributed to driver", () => {
  const p = data([
    trip("1", "2026-11-01"),
    trip("2", "2026-11-01", { vehicle: "А002АА77" }),
  ]);
  const fs = { ...M.emptyFilters(), drivers: ["Водитель А"] };
  const a = M.analyze(p, fs, "2026-11-01", "2026-11-01");
  assert.equal(M.groups(p, a, "driver")[0].days, 1);
  assert.equal(a.sat_km, null);
  assert.equal(a.movementDays, null);
});
test("comparison uses preceding full calendar month, quarter, and arbitrary interval", () => {
  assert.deepEqual(M.previousPeriod("2026-11-01", "2026-11-30"), [
    "2026-10-01",
    "2026-10-31",
  ]);
  assert.deepEqual(M.previousPeriod("2026-10-01", "2026-12-31"), [
    "2026-07-01",
    "2026-09-30",
  ]);
  assert.deepEqual(M.previousPeriod("2026-11-05", "2026-11-07"), [
    "2026-11-02",
    "2026-11-04",
  ]);
});
test("swap evaluates both assignments together, missing tariff prevents recommendation", () => {
  const a = { revenue: 100, payout: 10, partner_payout: 30 },
    b = { revenue: 200, payout: 20, partner_payout: 100 };
  assert.deepEqual(M.swapResult(a, b), {
    revenue: 300,
    current: 190,
    alternative: 250,
    value: 60,
    percent: (60 / 190) * 100,
  });
  assert.equal(M.swapResult(a, { ...b, payout: null }).alternative, null);
});
test("duplicate IDs are surfaced and not double counted", () => {
  const p = data([trip("1", "2026-11-01"), trip("1", "2026-11-01")]);
  assert.equal(
    M.quality(p).filter((q) => q.kind === "Дублирующаяся запись").length,
    1,
  );
  assert.equal(M.financial(p.trips).revenue, 300);
});
test("no telemetry is unknown movement, not zero movement", () => {
  const p = data([trip("1", "2026-11-01")]);
  const a = M.analyze(p, f(), "2026-11-01", "2026-11-01");
  assert.equal(a.movementDays, null);
  assert.equal(a.sat_km, null);
});
test("unassigned fuel cards do not become one repeated filling", () => {
  const p = data(),
    a = M.analyze(p, f(), "2026-11-01", "2026-11-01");
  const ops = [
    { vehicle: "", provider: "x", card: "1", date: "2026-11-01", liters: 30 },
    { vehicle: "", provider: "x", card: "2", date: "2026-11-01", liters: 30 },
  ];
  const issues = M.deviations(p, a, { movement_threshold: 10 }, ops);
  assert.equal(
    issues.filter((r) => r.kind === "Повторные заправки за день").length,
    0,
  );
  const ids = issues
    .filter((r) => r.kind === "Заправка без привязки")
    .map((i) => i.id);
  assert.equal(new Set(ids).size, 2);
});

test("incoming overnight trip contributes vehicle, driver and client days without reposting money", () => {
  const p = data([trip("1", "2026-10-31", { end: "2026-11-01T16:00:00" })]);
  const a = M.analyze(p, f(), "2026-11-01", "2026-11-02");
  for (const key of ["vehicle", "driver", "client"]) {
    const g = M.groups(p, a, key).find((x) => x.days > 0);
    assert.equal(g.days, 1);
    assert.equal(g.revenue, null);
    assert.equal(g.trips, 0);
    if (key === "driver") assert.equal(g.load, 50);
  }
});

test("declared company maps only to unique equivalent directory name, not an order carrier", () => {
  const p = data([trip("1", "2026-11-01")], {
    directories: {
      vehicles: [{ name: "А001АА77", company: "Чартер ООО" }],
      drivers: [],
      carriers: [{ id: "c", name: 'ООО "ЧАРТЕР"' }],
    },
  });
  assert.equal(p.vehicles[0].carrier, 'ООО "ЧАРТЕР"');
  assert.equal(
    M.category({ type: "Водительские услуги" }),
    "Прочие начисления",
  );
  assert.equal(M.isTrip(trip("2", "2026-11-01", { type: "Сервис" })), false);
});

test("a primary calendar status is not counted as an additional event", () => {
  const p = data([], {
    statuses: [
      {
        date: "2026-11-01",
        kind: "vehicle",
        entity: "А001АА77",
        reason: "Выходной",
      },
    ],
  });
  const a = M.analyze(p, f(), "2026-11-01", "2026-11-01");
  assert.equal(a.events, 0);
  assert.equal(a.statuses[0].value, 1);
});
