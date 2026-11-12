import React, {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useState,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  Truck,
  Users,
  Building2,
  ChartNoAxesCombined,
  CalendarDays,
  ShieldCheck,
  Fuel,
  Route,
  BookOpen,
  Settings2,
  ArrowUpRight,
  ArrowRight,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  SlidersHorizontal,
  Download,
  RefreshCw,
  X,
  Info,
  Menu,
  LogOut,
  ExternalLink,
  Plus,
  Check,
  AlertTriangle,
  ClipboardList,
  Database,
  PlugZap,
  UserCog,
} from "lucide-react";
import { Button } from "./vendor/stageshow/controls/button";
import { Card } from "./vendor/stageshow/parts/card";
import { Badge } from "./vendor/stageshow/controls/badge";
import { FleetStatus } from "./fleet-status.jsx";
import { RevenueReview } from "./revenue-review.jsx";
import { AnimatedMetric } from "./animated-metric.jsx";
import { RowBatches, ScrollRows, ScrollRowsContext, useScrollRows } from "./scroll-rows.jsx";
import * as M from "./model";
import { ChartSkeleton, ReportSkeleton, WorkspaceSkeleton } from "./workspace-loading";
import "./style.css";
const N = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }),
  satelliteKmFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 20 }),
  fmtSatelliteKm = (n) => (n == null ? "—" : satelliteKmFormat.format(n)),
  money = (n) => (n == null ? "—" : N.format(n) + " ₽"),
  fmt = (n) => (n == null ? "—" : N.format(n)),
  pct = (n) => (n == null ? "—" : fmt(n) + "%"),
  signedPct = (n) => (n > 0 ? "+" + pct(n) : pct(n)),
  signedMoney = (n) => (n > 0 ? "+" + money(n) : money(n)),
  litersText = (n) => fmt(n) + " л",
  short = (n) =>
    n == null
      ? "—"
      : Math.abs(n) >= 1e6
        ? fmt(n / 1e6) + " млн"
        : Math.abs(n) >= 1000
          ? fmt(n / 1000) + " тыс."
          : fmt(n);
const date = (s) =>
  s && M.validDay(s)
    ? new Date(s + "T12:00:00Z").toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "short",
      })
    : s || "—";
const weekday = new Intl.DateTimeFormat("ru-RU", { weekday: "short", timeZone: "UTC" });
const stamp = (s) =>
  s
    ? new Date(s).toLocaleString("ru-RU", {
        timeZone: "Europe/Moscow",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Дата не известна";
const nav = [
  ["overview", "Обзор", LayoutDashboard],
  ["fleet", "Автопарк", Truck],
  ["drivers", "Водители", Users],
  ["clients", "Клиенты", Building2],
  ["compare", "Сравнение", ChartNoAxesCombined],
  ["calendar", "Календарь", CalendarDays],
  ["planner", "Планировщик", ClipboardList],
  ["control", "Отклонения", ShieldCheck],
  ["fuel", "ГСМ", Fuel],
  ["routes", "Экономика маршрутов", Route],
  ["data", "Исходные данные", Database],
  ["directories", "Справочники", BookOpen],
  ["connections", "Подключения", PlugZap],
  ["settings", "Настройки", Settings2],
  ["users", "Пользователи", UserCog],
];
const hints = {
  overview: "Работа автопарка, деньги и то, что требует внимания",
  fleet: "Автомобили, загрузка и результаты перевозок",
  drivers: "Рабочие дни, заявки и структура начислений",
  clients: "Клиенты и экономика выполненных заказов",
  compare: "Сопоставляйте автомобили и отслеживайте изменения",
  calendar: "Каждый день на виду: работа, статусы и дополнительные события",
  planner: "Назначения водитель → автомобиль → маршрут с тарифом на дату",
  control: "Сигналы для проверки — с объяснением и историей решений",
  fuel: "Заправки по картам и нормативный расход отдельно от фактического",
  routes: "Сравнение совокупного результата двух назначений",
  data: "Заявки, назначения, статусы, спутник и топливные операции в одном месте",
  directories: "Исполнитель → тип транспорта → автомобили и водители",
  connections: "Состояние API и управляемое обновление внешних источников",
  settings: "Пороги контроля и правила интерпретации данных",
  users: "Роли, доступные автомобили и журнал действий",
};
let csrf = "";
let workspaceRequests = new AbortController();
const VehicleMapContext = createContext(new Map());
const livePreview = import.meta.env.MODE === "live-preview";
const unfilteredPages = ["settings", "directories", "routes", "connections", "users"];
const rankPages = ["fleet", "drivers", "clients"];

function useReportView(request, busy) {
  const [view, setView] = useState(null);
  useEffect(() => {
    if (busy || !request.p || !request.period) return;
    // Give the browser a paint for the new controls and loading state before computing the report.
    let commitFrame;
    const paintFrame = requestAnimationFrame(() => {
      commitFrame = requestAnimationFrame(() => {
        startTransition(() => setView(request));
      });
    });
    return () => {
      cancelAnimationFrame(paintFrame);
      if (commitFrame != null) cancelAnimationFrame(commitFrame);
    };
  }, [request, busy]);
  return view;
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

function SlidingTabs({ items, value, onChange, className = "" }) {
  const index = Math.max(0, items.findIndex(([id]) => id === value));
  return (
    <div
      className={`sliding-tabs ${className}`}
      style={{ "--tab-count": items.length, "--tab-index": index }}
    >
      <i className="sliding-tabs__indicator" aria-hidden="true" />
      {items.map(([id, label]) => (
        <button
          type="button"
          key={id}
          className={id === value ? "active" : ""}
          aria-pressed={id === value}
          onClick={() => onChange(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function VehicleCell({ name }) {
  const vehicles = useContext(VehicleMapContext),
    vehicle = name ? vehicles.get(name) : null;
  return (
    <span className="vehicle-cell">
      <strong>{name || "Без привязки"}</strong>
      <small>
        {vehicle?.carrier && vehicle.carrier !== M.UNKNOWN
          ? vehicle.carrier
          : "Принадлежность не установлена"}
      </small>
    </span>
  );
}

async function api(path, { asBlob = false, ...opt } = {}) {
  const signal = path === "logout"
    ? opt.signal
    : opt.signal
      ? AbortSignal.any([workspaceRequests.signal, opt.signal])
      : workspaceRequests.signal;
  const r = await fetch("/api/" + path, {
    ...opt,
    signal,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      ...opt.headers,
    },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    const error = new Error(body?.error || "Не удалось получить данные");
    error.status = r.status;
    throw error;
  }
  const token = r.headers.get("X-CSRF-Token");
  if (token) csrf = token;
  return asBlob ? r.blob() : r.json();
}
const B = ({ children, ...props }) => (
  <Button size="large" {...props}>
    {children}
  </Button>
);
const InfoNote = ({ children, tone = "" }) => (
  <div className={"info-note " + tone}>
    <Info size={16} />
    <span>{children}</span>
  </div>
);
function Empty({ children = "За выбранный период данных нет" }) {
  return (
    <div className="empty">
      <ChartNoAxesCombined size={26} />
      <strong>{children}</strong>
      <span>Измените период или выбранные фильтры.</span>
    </div>
  );
}
function Section({ title, subtitle, action, children, className = "" }) {
  return (
    <Card pad="large" className={"section " + className}>
      <div className="section-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}
function PeriodPicker({ period, onChange }) {
  const root = useRef(null);
  const [open, setOpen] = useState(false);
  const [part, setPart] = useState(0);
  const [month, setMonth] = useState(period[0].slice(0, 7));
  const [draft, setDraft] = useState(period.map(v => v.split('-').reverse().join('.')));
  useEffect(() => setDraft(period.map(v => v.split('-').reverse().join('.'))), [period]);
  useEffect(() => {
    const close = e => { if (!root.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, []);
  function commit(i) {
    if (draft[i] === period[i].split('-').reverse().join('.')) return;
    const value = draft[i].split('.').reverse().join('-');
    if (/^\d{4}-\d{2}-\d{2}$/.test(value) && M.validDay(value)) onChange(i, value);
    else setDraft(period.map(v => v.split('-').reverse().join('.')));
  }
  const first = new Date(month + '-01T12:00:00');
  const offset = (first.getDay() + 6) % 7;
  const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  function shift(n) {
    const d = new Date(first.getFullYear(), first.getMonth() + n, 1, 12);
    setMonth(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`);
  }
  return <div className="period-picker" ref={root} onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }}>
    <button type="button" aria-label="Открыть календарь" aria-expanded={open} onClick={() => { setMonth(period[part].slice(0,7)); setOpen(!open); }}><CalendarDays size={16}/></button>
    {[0,1].map(i => <React.Fragment key={i}>{i === 1 && <span>—</span>}<input type="text" inputMode="numeric" aria-label={i ? 'Конец периода' : 'Начало периода'} value={draft[i]} maxLength={10} onFocus={() => setPart(i)} onChange={e => setDraft(d => d.map((v,j) => j === i ? e.target.value : v))} onBlur={() => commit(i)} onKeyDown={e => { if (e.key === 'Enter') { commit(i); if (!i) root.current.querySelectorAll('input')[1].focus(); } }}/></React.Fragment>)}
    {open && <div className="range-calendar" role="dialog" aria-label="Выбор периода">
      <div className="range-parts">{['Начало','Конец'].map((label,i) => <button key={label} className={part === i ? 'selected' : ''} onClick={() => { setPart(i); setMonth(period[i].slice(0,7)); }}>{label}<small>{period[i].split('-').reverse().join('.')}</small></button>)}</div>
      <div className="range-month"><button aria-label="Предыдущий месяц" onClick={() => shift(-1)}><ChevronLeft size={16}/></button><span>{first.toLocaleDateString('ru-RU',{month:'long',year:'numeric'})}</span><button aria-label="Следующий месяц" onClick={() => shift(1)}><ChevronRight size={16}/></button></div>
      <div className="range-days">{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(d => <small key={d}>{d}</small>)}{Array.from({length:offset},(_,i) => <span key={'blank'+i}/>)}{Array.from({length:days},(_,i) => { const value = `${month}-${String(i+1).padStart(2,'0')}`; return <button key={value} className={period.includes(value) ? 'selected' : value > period[0] && value < period[1] ? 'in-range' : ''} aria-label={value} onClick={() => { onChange(part,value); if (part === 0) setPart(1); else setOpen(false); }}>{i+1}</button>; })}</div>
      <p>{part === 0 ? 'Выберите начало периода' : 'Выберите конец периода'}</p>
    </div>}
  </div>;
}
function Multi({ id, label, items, value, onChange, open, onToggle, onDismiss, fitViewport }) {
  const [search, setSearch] = useState("");
  const root = useRef(null);
  const panel = useRef(null);
  const searchRef = useRef(null);
  useLayoutEffect(() => {
    if (!open || !fitViewport) return;
    const place = () => {
      const bounds = root.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - bounds.bottom;
      root.current.dataset.placement = spaceBelow < panel.current.offsetHeight + 12 && bounds.top > spaceBelow
        ? "above"
        : "below";
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, fitViewport]);
  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => searchRef.current?.focus({ preventScroll: true }));
    const close = (event) => {
      if (!root.current?.contains(event.target)) onDismiss?.();
    };
    if (onDismiss) document.addEventListener("pointerdown", close);
    return () => {
      cancelAnimationFrame(frame);
      if (onDismiss) document.removeEventListener("pointerdown", close);
    };
  }, [open, onDismiss]);
  const list = items
    .map((i) => (typeof i === "string" ? { value: i, label: i } : i))
    .filter((i) => i.label.toLowerCase().includes(search.toLowerCase()));
  return (
    <div
      ref={root}
      className={"multi " + (value.length ? "is-active" : "")}
      data-open={open ? "true" : "false"}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          onToggle?.(id, false);
          e.currentTarget.querySelector(".multi-trigger")?.focus();
        }
      }}
    >
      <button
        id={id}
        type="button"
        className="multi-trigger"
        aria-expanded={open}
        onClick={() => onToggle?.(id, !open)}
      >
        {label}
        {value.length > 0 && <span className="count"><AnimatedMetric value={value.length} format={fmt} integer /></span>}
        <ChevronDown size={14} />
      </button>
      <div
        ref={panel}
        className="multi-pop"
        aria-hidden={!open}
        inert={open ? undefined : ""}
      >
        <div className="search-input">
          <Search size={15} />
          <input
            ref={searchRef}
            aria-label={"Поиск: " + label}
            placeholder="Поиск…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="multi-actions">
          <button
            type="button"
            onClick={() =>
              onChange([...new Set([...value, ...list.map((i) => i.value)])])
            }
          >
            Выбрать все
          </button>
          <button type="button" onClick={() => onChange([])}>Очистить</button>
        </div>
        <div className="multi-list">
          {list.map((i, index) => (
            <React.Fragment key={i.value}>
              {i.group && i.group !== list[index - 1]?.group && (
                <div className="multi-group">{i.group}</div>
              )}
              <label>
                <input
                  type="checkbox"
                  checked={value.includes(i.value)}
                  onChange={(e) =>
                    onChange(
                      e.target.checked
                        ? [...value, i.value]
                        : value.filter((v) => v !== i.value),
                    )
                  }
                />
                <span>
                  {i.label}
                  {i.note && <small>{i.note}</small>}
                </span>
              </label>
            </React.Fragment>
          ))}
          {!list.length && <p>Ничего не найдено</p>}
        </div>
      </div>
    </div>
  );
}
function SelectMenu({ name, value, defaultValue = "", onChange, options, ariaLabel, required = false, disabled = false, placeholder = "Выберите" }) {
  const controlled = value !== undefined;
  const [localValue, setLocalValue] = useState(defaultValue);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const root = useRef(null);
  const searchRef = useRef(null);
  const current = controlled ? value : localValue;
  const normalized = options.map((option) => typeof option === "string" ? { value: option, label: option } : option);
  const selected = normalized.find((option) => option.value === current);
  const visible = normalized.filter((option) => option.label.toLowerCase().includes(search.toLowerCase()));
  useEffect(() => {
    if (!open) return;
    const close = (event) => {
      if (!root.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    requestAnimationFrame(() => searchRef.current?.focus());
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  const choose = (next) => {
    if (!controlled) setLocalValue(next);
    onChange?.({ target: { value: next } });
    setOpen(false);
    setSearch("");
  };
  return (
    <div ref={root} className="select-menu" data-open={open ? "true" : "false"} onKeyDown={(event) => {
      if (event.key === "Escape" && open) {
        event.preventDefault();
        setOpen(false);
        root.current.querySelector(".select-menu-trigger")?.focus();
      }
    }}>
      {name && <input className="select-menu-input" tabIndex={-1} aria-hidden="true" name={name} value={current} required={required} onChange={() => {}} />}
      <button type="button" className="select-menu-trigger" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} disabled={disabled} onClick={() => setOpen((state) => !state)}>
        <span className={selected ? "" : "placeholder"}>{selected?.label || placeholder}</span>
        <ChevronDown size={14} />
      </button>
      <div className="select-menu-pop" aria-hidden={!open} inert={open ? undefined : ""}>
        <div className="search-input">
          <Search size={15} />
          <input ref={searchRef} aria-label={`Поиск: ${ariaLabel || placeholder}`} placeholder="Поиск…" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
        <div className="select-menu-list" role="listbox" aria-label={ariaLabel}>
          {visible.map((option) => (
            <button type="button" role="option" aria-selected={option.value === current} key={option.value} onClick={() => choose(option.value)}>
              <span>{option.label}</span>
              {option.value === current && <Check size={15} />}
            </button>
          ))}
          {!visible.length && <p>Ничего не найдено</p>}
        </div>
      </div>
    </div>
  );
}
function DataTable({ rows, columns, onRow, title = "Данные", downloadRows }) {
  const loading = rows === null;
  rows ??= EMPTY_ROWS;
  const [search, setSearch] = useState(""),
    [sort, setSort] = useState(null),
    [downloading, setDownloading] = useState(false),
    [downloadError, setDownloadError] = useState(""),
    vehicles = useContext(VehicleMapContext);
  const filtered = useMemo(() => {
    const query = search.toLowerCase();
    const matching = query ? rows.filter((r) =>
      columns.some((c) => {
        const source = c.vehicle ? vehicles.get(r[c.key])?.carrier : "";
        return `${r[c.key] ?? ""} ${source || ""}`.toLowerCase().includes(query);
      }),
    ) : rows;
    if (!sort) return matching;
    const { key, dir } = sort;
    return [...matching].sort((a, b) => {
      const av = a[key],
        bv = b[key];
      if (av == null) return 1;
      if (bv == null) return -1;
      return (
        dir *
        (typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv), "ru"))
      );
    });
  }, [rows, columns, search, sort, vehicles]);
  const selection = useMemo(() => ({ search, sort }), [search, sort]);
  const [visible, sentinel] = useScrollRows(filtered.length, selection, TABLE_BATCH_SIZE, !search && !sort ? title : null);
  const renderRows = useCallback((start, end) => {
    const rowKeyCounts = new Map();
    return filtered.slice(start, end).map((r, index) => {
      const id = r.record_id ?? r.id;
      const subject = r.name ?? r.vehicle ?? r.entity;
      const identity = id != null
        ? `id:${id}`
        : r.date && subject != null
          ? `day:${r.date}|${subject}|${r.reason ?? ""}`
          : r.name != null ? `name:${r.name}|${r.reason ?? ""}` : `row:${index}`;
      const occurrence = rowKeyCounts.get(identity) ?? 0;
      rowKeyCounts.set(identity, occurrence + 1);
      return (
        <tr
          key={`${identity}:${occurrence}`}
          onClick={() => onRow?.(r)}
          onKeyDown={(e) => {
            if (onRow && e.key === "Enter") onRow(r);
          }}
          tabIndex={onRow ? 0 : undefined}
          className={onRow ? "clickable" : ""}
        >
          {columns.map((c) => (
            <td key={c.key} className={c.numeric ? "number" : ""}>
              {c.vehicle ? (
                <VehicleCell name={r[c.key]} />
              ) : c.render ? (
                c.render(r)
              ) : (
                (r[c.key] ?? "—")
              )}
            </td>
          ))}
        </tr>
      );
    });
  }, [filtered, columns, onRow]);
  async function download() {
    setDownloading(true);
    setDownloadError("");
    try {
      await downloadRows(filtered, vehicles);
    } catch (error) {
      if (error.name !== "AbortError")
        setDownloadError(error.status ? error.message : "Не удалось скачать Excel. Попробуйте ещё раз.");
    } finally {
      setDownloading(false);
    }
  }
  return (
    <div className="data-table" aria-busy={loading || undefined}>
      <div className="table-tools">
        <div className="search-input">
          <Search size={16} />
          <input
            aria-label={"Поиск в таблице " + title}
            placeholder="Поиск в таблице"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {!loading && <span className="muted">Всего <AnimatedMetric value={filtered.length} format={fmt} integer /></span>}
        {downloadRows && (
          <B size="medium" type="button" icon={<Download size={16} />}
             onClick={download} disabled={!filtered.length || downloading}>
            <span>{downloading ? "Готовим Excel…" : "Скачать Excel"}</span>
          </B>
        )}
      </div>
      {downloadError && <p className="error" role="alert">{downloadError}</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((c) => c.sortable === false ? (
                <th key={c.key}>{c.label}</th>
              ) : (
                <th
                  key={c.key}
                  aria-sort={
                    sort?.key === c.key
                      ? sort.dir === 1
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    onClick={() =>
                      setSort({
                        key: c.key,
                        dir: sort?.key === c.key ? -sort.dir : 1,
                      })
                    }
                  >
                    {c.label}
                    <span>
                      {sort?.key === c.key
                        ? sort.dir === 1
                          ? " ↑"
                          : " ↓"
                        : " ↕"}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <RowBatches visible={visible} batchSize={TABLE_BATCH_SIZE} render={renderRows} />
          </tbody>
        </table>
      </div>
      {loading && <ScrollRows />}
      {!loading && !filtered.length && <Empty />}
      {visible < filtered.length && <ScrollRows sentinel={sentinel} />}
    </div>
  );
}
const EMPTY_ROWS = [];
const TABLE_BATCH_SIZE = 30;
const CALENDAR_BATCH_SIZE = 20;
const col = (key, label, format = fmt, integer = false) => ({
  key,
  label,
  numeric: true,
  render: (r) => <AnimatedMetric value={r[key]} format={format} integer={integer} />,
});
const tripCols = [
  { key: "id", label: "Заявка" },
  { key: "date", label: "Дата" },
  { key: "vehicle", label: "Автомобиль", vehicle: true },
  { key: "driver", label: "Водитель" },
  { key: "client", label: "Клиент" },
  { key: "category", label: "Категория" },
  col("revenue", "Выручка", money),
  col("payout", "Выплата", money),
  col("km", "ТТ, км"),
  col("hours", "ТТ, ч"),
];
const groupCols = (vehicle = false) => [
  { key: "name", label: vehicle ? "Автомобиль" : "Наименование", vehicle },
  col("revenue", "Выручка", money),
  col("payout", "Выплаты", money),
  col("balance", "Марж. результат", money),
  col("margin", "Доля результата", pct),
  col("trips", "Заявки", fmt, true),
  col("days", "Рабочие дни", fmt, true),
  col("average", "Средний чек", money),
  col("km", "ТТ, км"),
  col("hours", "ТТ, ч"),
];
const Chart = React.lazy(() => import("./money-chart"));

function MoneyChart({ data, bar = false, onSelect }) {
  const reduced = useReducedMotion();
  if (!data.length) return <Empty />;
  return (
    <React.Suspense fallback={<ChartSkeleton />}>
      <Chart {...{ data, bar, onSelect, reduced, date, short, money }} />
    </React.Suspense>
  );
}
function LegendRow() {
  return (
    <div className="legend">
      <span>
        <i style={{ background: "#477dc6" }} />
        Выручка
      </span>
      <span>
        <i style={{ background: "#89b9a7" }} />
        Выплаты
      </span>
    </div>
  );
}
function KPI({ label, raw, format = fmt, integer = false, sub, change, onClick, primary = false, tip }) {
  return (
    <Card pad="large" className={"kpi " + (primary ? "primary-kpi" : "")}>
      <div className="kpi-label">
        {label}
        <span title={tip || (typeof sub === "string" ? sub : undefined)}>
          <Info size={13} />
        </span>
      </div>
      <button className="kpi-value" onClick={onClick}>
        <AnimatedMetric value={raw} format={format} integer={integer} />
        <ArrowUpRight size={19} />
      </button>
      <div className="kpi-bottom">
        {change !== undefined && change !== null && (
          <span className={"delta " + (change >= 0 ? "positive" : "negative")}>
            <AnimatedMetric value={change} format={signedPct} />
          </span>
        )}
        <span>{sub}</span>
      </div>
    </Card>
  );
}
function Drawer({ title, children, onClose, size = "wide" }) {
  const ref = useRef();
  const opener = useRef(document.activeElement);
  const [opened, setOpened] = useState(false);
  const closing = useRef(false);
  const reduced = useReducedMotion();
  const requestClose = () => {
    if (closing.current) return;
    closing.current = true;
    setOpened(false);
    window.setTimeout(() => {
      onClose();
      opener.current?.focus?.({ preventScroll: true });
    }, reduced ? 100 : 280);
  };
  useEffect(() => {
    const el = ref.current;
    const body = document.body;
    const root = document.documentElement;
    const scrollY = window.scrollY;
    const scrollbarWidth = window.innerWidth - root.clientWidth;
    const previousBodyStyles = {
      position: body.style.position,
      top: body.style.top,
      left: body.style.left,
      right: body.style.right,
      width: body.style.width,
      paddingRight: body.style.paddingRight,
    };
    root.classList.add("drawer-open");
    body.classList.add("drawer-open");
    body.style.position = "fixed";
    body.style.top = `-${scrollY}px`;
    body.style.left = "0";
    body.style.right = "0";
    body.style.width = "100%";
    if (scrollbarWidth > 0) body.style.paddingRight = `${scrollbarWidth}px`;
    el.showModal();
    requestAnimationFrame(() => setOpened(true));
    return () => {
      if (el.open) el.close();
      root.classList.remove("drawer-open");
      body.classList.remove("drawer-open");
      Object.assign(body.style, previousBodyStyles);
      window.scrollTo({ top: scrollY, left: 0, behavior: "instant" });
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`drawer drawer-${size} ${opened ? "is-open" : "is-closing"}`}
      onCancel={(e) => {
        e.preventDefault();
        requestClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
    >
      <div className="drawer-inner">
        <header>
          <div>
            <span className="eyebrow">Детализация</span>
            <h2>{title}</h2>
          </div>
          <B
            aria-label="Закрыть детализацию"
            icon={<X size={18} />}
            onClick={requestClose}
          />
        </header>
        {children}
      </div>
    </dialog>
  );
}
function App() {
  const navRef = useRef(null);
  const menuButtonRef = useRef(null);
  const scrollPositions = useRef(new Map());
  const restorePage = useRef(null);
  const [navCapsule, setNavCapsule] = useState({ y: 0, height: 40, visible: false });
  const [payload, setPayload] = useState(null),
    [error, setError] = useState(""),
    [logoutBusy, setLogoutBusy] = useState(false),
    [logoutError, setLogoutError] = useState(""),
    [page, setPage] = useState(
      location.pathname.split("/").pop() || "overview",
    ),
    [adaptive, setAdaptive] = useState(() =>
      typeof matchMedia === "function"
        ? matchMedia("(max-width: 1023px)").matches
        : false,
    ),
    [mobile, setMobile] = useState(false),
    [busy, setBusy] = useState(true),
    [drawer, setDrawer] = useState(null);
  const user = payload?.user;
  const saved = useMemo(() => {
    try {
      return JSON.parse(sessionStorage.getItem("charter-filters") || "null");
    } catch {
      return null;
    }
  }, []);
  const [filters, setFilters] = useState({
      ...M.emptyFilters(),
      ...saved?.filters,
    }),
    [periodSelection, setPeriodSelection] = useState(() => ({
      period: saved?.period || null,
      anchor: saved?.periodAnchor || saved?.period?.[0],
    }));
  const { period, anchor: periodAnchor } = periodSelection;
  function setPeriod(next, anchor = next[0]) {
    setPeriodSelection((current) => {
      const samePeriod = current.period?.[0] === next[0] && current.period?.[1] === next[1];
      if (samePeriod && current.anchor === anchor) return current;
      return { period: samePeriod ? current.period : next, anchor };
    });
  }
  const [showMore, setShowMore] = useState(false),
    [openMulti, setOpenMulti] = useState(null),
    [unit, setUnit] = useState("day"),
    [compareMode, setCompareMode] = useState("objects"),
    [compareBy, setCompareBy] = useState("vehicle"),
    [calMode, setCalMode] = useState("vehicle"),
    [controlTab, setControlTab] = useState("signals"),
    [reviewFilter, setReviewFilter] = useState([]),
    [rankMetric, setRankMetric] = useState("revenue");
  useEffect(() => {
    const close = (event) => {
      if (!event.target.closest(".multi")) setOpenMulti(null);
      if (!event.target.closest(".filters")) setShowMore(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const query = matchMedia("(max-width: 1023px)");
    const update = () => {
      setAdaptive(query.matches);
      if (!query.matches) setMobile(false);
    };
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  useEffect(() => {
    if (!mobile) return;
    const close = (event) => {
      if (event.key === "Escape") {
        setMobile(false);
        menuButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [mobile]);
  useEffect(() => {
    if (!adaptive || !mobile) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [adaptive, mobile]);
  const multiProps = (id) => ({
    id,
    open: openMulti === id,
    onToggle: (key, nextOpen) => setOpenMulti(nextOpen ? key : null),
  });
  async function refresh(signal) {
    setBusy(true);
    try {
      const result = await api("charter?view=workspace", { signal });
      if (signal?.aborted) return;
      setPayload(result);
      if (
        !period ||
        (!payload && saved?.dataset !== (result.demo?.version || "snapshot"))
      ) {
        let last = "";
        for (const { date } of result.data.trips)
          if (date > last && M.validDay(date)) last = date;
        last ||= "2026-11-07";
        setFilters(M.emptyFilters());
        if (result.demo) setPeriod(result.demo.period);
        else setPeriod(M.periodFor(last, "month"), last);
      }
      setError("");
    } catch (e) {
      if (signal?.aborted) return;
      if (e.status === 401) {
        if (import.meta.env.DEV) location.assign("http://127.0.0.1:8776" + location.pathname);
        else location.reload();
        return;
      }
      setError(e.message);
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    const restore = (event) => {
      if (event.persisted) location.reload();
    };
    window.addEventListener("pageshow", restore);
    return () => {
      controller.abort();
      window.removeEventListener("pageshow", restore);
    };
  }, []);
  async function logout() {
    setLogoutBusy(true);
    setLogoutError("");
    workspaceRequests.abort();
    try {
      await api("logout", { method: "POST" });
      location.replace(location.pathname);
    } catch (error) {
      if (error.status === 401) {
        location.replace(location.pathname);
        return;
      }
      workspaceRequests = new AbortController();
      setLogoutError(error.message);
      setLogoutBusy(false);
    }
  }
  useEffect(() => {
    const previous = history.scrollRestoration;
    history.scrollRestoration = "manual";
    return () => {
      history.scrollRestoration = previous;
    };
  }, []);
  useEffect(() => {
    const pop = () => {
      selectPage(location.pathname.split("/").pop() || "overview");
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [page]);
  useEffect(() => {
    if (period && payload)
      sessionStorage.setItem(
        "charter-filters",
        JSON.stringify({
          filters,
          period,
          periodAnchor,
          dataset: payload.demo?.version || "snapshot",
        }),
      );
  }, [filters, period, periodAnchor, !!payload, payload?.demo?.version]);
  function selectPage(next) {
    setMobile(false);
    if (next === page) {
      return;
    }
    if (restorePage.current !== page) scrollPositions.current.set(page, window.scrollY);
    restorePage.current = next;
    window.scrollTo(0, 0);
    setPage(next);
    setOpenMulti(null);
    setShowMore(false);
    setDrawer(null);
  }
  function go(next) {
    if (next !== page) history.pushState({}, "", `/${next}`);
    selectPage(next);
  }
  const workspace = useMemo(
    () => (payload ? M.prepare(payload.data) : null),
    [payload?.data],
  );
  const request = useMemo(() => ({
    p: workspace,
    filters,
    period,
    page,
    settings: payload?.state.settings,
    fuel: payload?.fuel,
  }), [workspace, filters, period, page, payload?.state.settings, payload?.fuel]);
  const view = useReportView(request, busy);
  const pending = busy || view !== request;
  const { p, filters: reportFilters, period: reportPeriod, page: reportPage, settings, fuel } = view || {};
  const rowLimits = useMemo(() => new Map(), [p, reportFilters, reportPeriod, settings, fuel]);
  const scrollScope = useMemo(() => ({ page, limits: rowLimits }), [page, rowLimits]);
  const hasCurrentReport = reportPage === page;
  const a = useMemo(
    () => (p ? M.analyze(p, reportFilters, ...reportPeriod, settings, fuel) : null),
    [p, reportFilters, reportPeriod, settings, fuel],
  );
  const prev = useMemo(
    () =>
      p && reportPage === "overview"
        ? M.financial(M.postingRows(p, reportFilters, ...M.previousPeriod(...reportPeriod)))
        : null,
    [p, reportFilters, reportPeriod, reportPage],
  );
  const issues = useMemo(
    () => (p && (reportPage === "overview" || reportPage === "control")
      ? M.deviations(p, a, settings) : null),
    [p, a, settings, reportPage],
  );
  const q = useMemo(() => (p && reportPage === "control" ? M.quality(p) : []), [p, reportPage]);
  const groupKey =
    reportPage === "drivers" ? "driver" : reportPage === "clients" ? "client" : "vehicle";
  const groupRows = useMemo(
    () => (p && a && rankPages.includes(reportPage) ? M.groups(p, a, groupKey) : []),
    [p, a, reportPage, groupKey],
  );
  const overviewClients = useMemo(
    () => (reportPage === "overview" ? M.groups(p, a, "client").slice(0, 6) : []),
    [p, a, reportPage],
  );
  const timeline = useMemo(
    () => (reportPage === "overview" ? M.timeline(a, unit) : []),
    [a, reportPage, unit],
  );
  const comparisonRows = useMemo(() => {
    if (reportPage !== "compare") return [];
    if (compareMode === "objects") return M.groups(p, a, compareBy);
    return M.timeline(a, "month").map((r) => ({
      ...r,
      days: new Set(
        r.rows.filter(M.isTrip).flatMap((trip) =>
          M.daysBetween(...M.tripSpan(trip)).map((day) => trip.vehicle + "|" + day),
        ),
      ).size,
    }));
  }, [p, a, reportPage, compareMode, compareBy]);
  const reviews = payload?.state.reviews;
  const openSignals = useMemo(() => {
    if (!p) return 0;
    if (!issues) return M.deviationCount(p, a, settings, reviews);
    return issues.reduce((count, issue) => (
      ["Обосновано", "Исправлено"].includes(reviews[issue.id]?.status) ? count : count + 1
    ), 0);
  }, [p, a, settings, issues, reviews]);
  const issuesByKind = useMemo(() => {
    const kinds = new Map();
    if (reportPage !== "overview") return kinds;
    for (const issue of issues) {
      if (!kinds.has(issue.kind)) kinds.set(issue.kind, []);
      kinds.get(issue.kind).push(issue);
    }
    return kinds;
  }, [issues, reportPage]);
  const opts = useMemo(() => workspace && M.available(workspace, filters), [workspace, filters]);
  const vehicleOptions = useMemo(() => opts && [...opts.vehicles]
    .sort((a, b) => (a.carrier + a.name).localeCompare(b.carrier + b.name, "ru"))
    .map((v) => ({ value: v.name, label: v.name, group: v.carrier, note: v.brand })), [opts]);
  const driverOptions = useMemo(() => opts?.drivers.map((v) => ({
    value: v.name, label: v.name, group: v.carrier,
  })), [opts]);
  const directories = useMemo(() => {
    if (!workspace) return null;
    const carriers = new Set([
      ...workspace.vehicles.map((v) => v.carrier),
      ...workspace.drivers.map((v) => v.carrier),
    ]);
    const types = new Set();
    const clients = new Set();
    for (const trip of workspace.trips) {
      carriers.add(trip.carrier || M.UNKNOWN);
      clients.add(trip.client || M.UNKNOWN);
      if (M.isTrip(trip)) types.add(trip.type || M.UNKNOWN);
    }
    return { carriers: [...carriers].sort(), types: [...types].sort(), clients: [...clients].sort() };
  }, [workspace]);
  function filter(key, value) {
    setFilters((f) => ({
      ...f,
      [key]: value,
      ...(key === "carriers" || key === "ownership"
        ? { vehicles: [], drivers: [] }
        : {}),
    }));
  }
  function updatePeriod(index, value) {
    if (!M.validDay(value)) return;
    const next = [...period];
    next[index] = value;
    if (next[0] > next[1]) next[1 - index] = value;
    if (M.daysBetween(...next).length > 730)
      next[1 - index] = M.addDays(value, index === 0 ? 729 : -729);
    setPeriod(next, value);
  }
  async function save(body) {
    const state = await api("charter/state", {
      method: "PUT",
      body: JSON.stringify({ ...body, revision: payload.state.revision }),
    });
    setPayload((old) => ({ ...old, state }));
    return state;
  }
  function details(title, rows) {
    setDrawer({ type: "trips", title, rows });
  }
  function daysDetails(title, days) {
    setDrawer({ type: "days", title, days });
  }
  async function changeStatus(path, method, body) {
    try {
      await api(path, { method, body: JSON.stringify(body) });
    } catch (error) {
      if (error.status === 409) await refresh();
      throw error;
    }
    await refresh();
  }
  async function saveStatus(day, dates, reason, note) {
    const cat = workspace.directories[calMode === "driver" ? "drivers" : "vehicles"]
      .find((r) => r.name === day.name && !r.archived && !r.merged_into);
    if (!cat) throw Error("Для сохранения нужна активная запись в справочнике.");
    const days = Object.fromEntries(dates.map((date) => [date, []]));
    for (const row of workspace.statuses) {
      if (row.kind === calMode && row.entity_id === cat.id && Object.hasOwn(days, row.date)) {
        days[row.date].push(row.delete_token);
      }
    }
    await changeStatus("manual/statuses", "PUT", {
      days, kind: calMode, entity_id: cat.id, reason, note,
    });
  }
  useLayoutEffect(() => {
    const update = () => {
      const root = navRef.current;
      const selected = root?.querySelector("a.active");
      if (!root || !selected) return;
      setNavCapsule({
        y: selected.offsetTop,
        height: selected.offsetHeight,
        visible: true,
      });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [page, user?.role, !!view]);
  useLayoutEffect(() => {
    if (!pending && restorePage.current === page) {
      restorePage.current = null;
      window.scrollTo(0, scrollPositions.current.get(page) || 0);
    }
  }, [page, pending]);
  const visibleNav = nav.filter(([id]) => id !== "users" || user?.role === "admin"),
    active = visibleNav.find((n) => n[0] === page) || visibleNav[0],
    title = active[0] === "overview" ? "Обзор автопарка" : active[1];
  if (!a && (!error || busy)) {
    return <WorkspaceSkeleton page={active[0]} title={title} hint={hints[page]} filtered={!unfilteredPages.includes(page)} />;
  }
  if (!p || !a)
    return (
      <div className="loading">
        <p>{error || "Загрузка данных…"}</p>
        <B onClick={() => refresh()}>Повторить</B>
      </div>
    );
  const count = Object.values(filters).reduce((n, v) => n + v.length, 0),
    changed = (key) => M.delta(a[key], prev?.[key]).percent;
  const subnav = (id, label) => (
    <button onClick={() => go(id)}>
      {label}
      <ArrowRight size={14} />
    </button>
  );
  const finances = (
    <div className="kpi-grid">
      <KPI
        label="Выручка"
        raw={a.revenue}
        format={money}
        change={changed("revenue")}
        sub="к предыдущему периоду"
        primary
        onClick={() => details("Выручка · исходные записи", a.rows)}
        tip="Сумма выручки всех выбранных записей. Учёт по дате начала заявки."
      />
      <KPI
        label="Выплаты по заявкам"
        raw={a.payout}
        format={money}
        sub={
          a.payout_percent === null
            ? "Нет базы для расчёта доли"
            : <><AnimatedMetric value={a.payout_percent} format={pct} /> от выручки</>
        }
        onClick={() => details("Выплаты · исходные записи", a.rows)}
        tip={a.payout_percent === null ? undefined : pct(a.payout_percent) + " от выручки"}
      />
      <KPI
        label="Маржинальный результат"
        raw={a.balance}
        format={money}
        sub={<><AnimatedMetric value={a.margin} format={pct} /> от выручки · без ГСМ</>}
        change={changed("balance")}
        onClick={() => details("Выручка минус выплаты", a.rows)}
        tip="Выручка минус выплаты по заявкам. Без ГСМ, ремонта, лизинга и амортизации; не чистая прибыль."
      />
      <KPI
        label="Загрузка по дням"
        raw={a.load}
        format={pct}
        sub={
          <>
            <AnimatedMetric value={a.workDays} format={fmt} integer /> из{" "}
            <AnimatedMetric value={a.days.length} format={fmt} integer /> авто-дней
          </>
        }
        onClick={() =>
          daysDetails(
            "Рабочие дни по ТТ",
            a.days.filter((d) => d.status === "Работа"),
          )
        }
        tip="Рабочие авто-дни / календарные авто-дни выбранных автомобилей. День с несколькими заявками считается один раз."
      />
    </div>
  );
  const statusPanel = (
    <Section
      title="Как работал автопарк"
      subtitle="Основной статус · доля от выбранных авто-дней"
      action={subnav("calendar", "Календарь")}
    >
      <FleetStatus
        analysis={a}
        format={fmt}
        formatPercent={pct}
        onSelect={daysDetails}
      />
    </Section>
  );
  return (
    <VehicleMapContext.Provider value={p.vehicleMap}>
      <div className="workspace">
      <aside
        id="workspace-navigation"
        className={"sidebar " + (mobile ? "open" : "")}
        aria-hidden={adaptive ? !mobile : undefined}
        inert={adaptive && !mobile ? "" : undefined}
      >
        <a
          href="/overview"
          className="wordmark"
          onClick={(e) => {
            e.preventDefault();
            go("overview");
          }}
        >
          CharterStats<span> / </span>
        </a>
        <nav aria-label="Основная навигация" ref={navRef}>
          <i
            className="nav-capsule"
            aria-hidden="true"
            style={{
              transform: `translateY(${navCapsule.y}px)`,
              height: navCapsule.height,
              opacity: navCapsule.visible ? 1 : 0,
            }}
          />
          {visibleNav.map(([id, label, Icon]) => (
            <React.Fragment key={id}>
              {["overview", "calendar", "data", "directories"].includes(id) && (
                <div className="nav-caption">
                  {id === "overview"
                    ? "Аналитика"
                    : id === "calendar"
                      ? "Управление"
                      : id === "data"
                        ? "Данные"
                        : "Рабочее пространство"}
                </div>
              )}
              <a
                href={"/" + id}
                onClick={(e) => {
                  if (!e.metaKey && !e.ctrlKey) {
                    e.preventDefault();
                    go(id);
                  }
                }}
                className={page === id ? "active" : ""}
                aria-current={page === id ? "page" : undefined}
              >
                <Icon size={18} />
                <span>{label}</span>
                {id === "control" && openSignals > 0 && (
                  <small><AnimatedMetric value={openSignals} format={fmt} integer /></small>
                )}
              </a>
            </React.Fragment>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="account">
            <div className="avatar">{user.name.slice(0, 1)}</div>
            <div>
              <b>{user.name}</b>
              <small>
                {user.role === "admin"
                  ? "Руководитель"
                  : user.role === "logist"
                    ? "Логист"
                    : "Наблюдатель"}
              </small>
            </div>
            <button
              aria-label="Выйти"
              onClick={logout}
              disabled={logoutBusy}
            >
              <LogOut size={16} />
            </button>
          </div>
          {logoutError && <p className="error" role="alert">{logoutError}</p>}
        </div>
      </aside>
      {adaptive && mobile && (
        <button
          className="mobile-scrim"
          aria-label="Закрыть меню"
          onClick={() => {
            setMobile(false);
            menuButtonRef.current?.focus();
          }}
        />
      )}
      <div className="main-wrap">
        <header className="topbar">
          <span className="topbar-context">
            Рабочее пространство <ChevronRight size={13} /> <b>{active[1]}</b>
          </span>
          <a
            href="/overview"
            className="topbar-brand wordmark"
            onClick={(event) => {
              event.preventDefault();
              go("overview");
            }}
          >
            CharterStats<span> / </span>
          </a>
          <div className="topbar-controls">
            <span className="environment">
              {livePreview
                ? "Локальный просмотр"
                : payload.demo
                ? "ДЕМО"
                : payload.local_preview
                  ? "Локальная копия"
                  : "Рабочая база"}
            </span>
            <B
              className="refresh-button"
              aria-label="Перечитать"
              icon={<RefreshCw size={14} className={busy ? "spin" : ""} />}
              disabled={busy}
              onClick={() => refresh()}
            >
              Перечитать
            </B>
            <button
              ref={menuButtonRef}
              className="mobile-toggle"
              aria-label={mobile ? "Закрыть меню" : "Открыть меню"}
              aria-expanded={mobile}
              aria-controls="workspace-navigation"
              onClick={() => setMobile(!mobile)}
            >
              <span className="menu-icon" aria-hidden="true">
                <Menu className="menu-icon__open" size={24} />
                <X className="menu-icon__close" size={25} />
              </span>
            </button>
          </div>
        </header>
        <main>
          <div key={page} className="page-content">
          {payload.demo && (
            <div className="demo-banner" role="status">
              <div>
                <strong>Демонстрационный режим</strong>
                <span>
                  Все компании, люди, операции и цифры вымышлены. Можно
                  пробовать фильтры и изменять записи.
                </span>
              </div>
              <div className="demo-actions">
                <button
                  onClick={() => {
                    setFilters(M.emptyFilters());
                    setPeriod(payload.demo.period);
                    go("overview");
                  }}
                >
                  Ноябрь · обзор
                </button>
                <button
                  onClick={() => {
                    setFilters(M.emptyFilters());
                    setPeriod(["2026-01-01", "2026-11-30"]);
                    setCompareMode("periods");
                    go("compare");
                  }}
                >
                  Динамика за год
                </button>
              </div>
            </div>
          )}
          <div className="page-heading">
            <div>
              <span className="eyebrow">CHARTER / ANALYTICS</span>
              <h1>{title}</h1>
              <p>{hints[page]}</p>
            </div>
            <div className="heading-meta">
              <Badge dot tone="neutral">
                {livePreview
                  ? "Рабочий API · только чтение"
                  : payload.demo
                  ? "Вымышленные данные"
                  : payload.local_preview
                    ? "Локальный снимок API"
                    : "Данные приложения"}
              </Badge>
              <small>
                {workspace.meta?.imported_at
                  ? "Обновление: " + stamp(workspace.meta.imported_at) + " МСК"
                  : "Дата обновления источника не указана"}
              </small>
            </div>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {!unfilteredPages.includes(page) && (
            <div className="filters">
              <div className="filter-line">
                <PeriodPicker period={period} onChange={updatePeriod} />
                <Multi
                  {...multiProps("carriers")}
                  label="Исполнители"
                  items={directories.carriers}
                  value={filters.carriers}
                  onChange={(v) => filter("carriers", v)}
                />
                <Multi
                  {...multiProps("vehicles")}
                  label="Автомобили"
                  items={vehicleOptions}
                  value={filters.vehicles}
                  onChange={(v) => filter("vehicles", v)}
                />
                <B
                  className="filters-toggle"
                  icon={<SlidersHorizontal size={15} />}
                  aria-expanded={showMore}
                  onClick={() => {
                    setOpenMulti(null);
                    setShowMore(!showMore);
                  }}
                >
                  Фильтры{count > 0 && <> · <AnimatedMetric value={count} format={fmt} integer /></>}
                </B>
              </div>
              <div className="filter-bottom">
                <SlidingTabs
                  className="period-presets"
                  items={[
                    ["day", "День"],
                    ["week", "Неделя"],
                    ["month", "Месяц"],
                    ["quarter", "Квартал"],
                    ["year", "Год"],
                  ]}
                  value={
                    ["day", "week", "month", "quarter", "year"].find(
                      (kind) =>
                        JSON.stringify(M.periodFor(periodAnchor, kind)) ===
                        JSON.stringify(period),
                    ) || "custom"
                  }
                  onChange={(kind) =>
                    setPeriod(M.periodFor(periodAnchor, kind), periodAnchor)
                  }
                />
                <span>
                  {date(period[0])} — {date(period[1])} ·{" "}
                  {M.daysBetween(...period).length} дней
                </span>
                {count > 0 && (
                  <button
                    className="clear"
                    onClick={() => setFilters(M.emptyFilters())}
                  >
                    Сбросить выбор <X size={13} />
                  </button>
                )}
              </div>
              {showMore && (
                <div className="extra-filters">
                  <Multi
                    {...multiProps("drivers")}
                    label="Водители"
                    items={driverOptions}
                    value={filters.drivers}
                    onChange={(v) => filter("drivers", v)}
                  />
                  <Multi
                    {...multiProps("types")}
                    label="Типы транспорта"
                    items={directories.types}
                    value={filters.types}
                    onChange={(v) => filter("types", v)}
                  />
                  <Multi
                    {...multiProps("clients")}
                    label="Клиенты"
                    items={directories.clients}
                    value={filters.clients}
                    onChange={(v) => filter("clients", v)}
                  />
                  <Multi
                    {...multiProps("statuses")}
                    label="Статусы дней"
                    items={Object.keys(M.STATUS_COLORS)}
                    value={filters.statuses}
                    onChange={(v) => filter("statuses", v)}
                  />
                  <Multi
                    {...multiProps("ownership")}
                    label="Принадлежность"
                    items={[
                      "Собственный парк",
                      "Привлечённые",
                      "Не установлено",
                    ]}
                    value={filters.ownership}
                    onChange={(v) => filter("ownership", v)}
                  />
                </div>
              )}
            </div>
          )}
          {pending && (!hasCurrentReport || busy) && (
            <span className="loading-announcement" role="status">Загрузка данных…</span>
          )}
          <div className={"report-body" + (pending ? " is-pending" : "")} aria-busy={pending}>
          {!hasCurrentReport && <ReportSkeleton page={active[0]} />}
          {hasCurrentReport && (
          <div className="report-skeleton-layer" aria-hidden="true">
            <ReportSkeleton page={active[0]} />
          </div>
          )}
          {hasCurrentReport && (
          <ScrollRowsContext.Provider value={scrollScope}>
          <div className="report-results" inert={pending ? "" : undefined} aria-hidden={pending || undefined}>
          {page === "overview" && (
            <>
              {finances}
              <div className="dashboard-grid">
                <Section
                  title="Выручка и выплаты"
                  subtitle="По дате начала заявки · финансовые строки без распределения по дням"
                  className="main-chart"
                  action={
                    <SlidingTabs
                      className="segments"
                      items={[["day", "По дням"], ["month", "По месяцам"]]}
                      value={unit}
                      onChange={setUnit}
                    />
                  }
                >
                  <div className="chart-summary">
                    <strong><AnimatedMetric value={a.revenue} format={money} /></strong>
                    <LegendRow />
                  </div>
                  <MoneyChart
                    data={timeline}
                    onSelect={(r) => details(r.name, r.rows)}
                  />
                  <div className="section-foot">
                    <span>
                      Средний чек <b><AnimatedMetric value={a.average} format={money} /></b>
                    </span>
                    <span>
                      Выручка / рабочий авто-день <b><AnimatedMetric value={a.revenue_day} format={money} /></b>
                    </span>
                  </div>
                </Section>
                {statusPanel}
              </div>
              <TelemetrySummary
                a={a}
                onDetails={() =>
                  setDrawer({
                    type: "telemetry",
                    title: "Пробег и время · спутниковые показания",
                  })
                }
              />
              <div className="work-strip">
                {[
                  [
                    "Заявки",
                    a.trips,
                    "Несколько заявок могут занимать один день",
                  ],
                  [
                    "Рабочие авто-дни ТТ",
                    a.workDays,
                    "Уникальные пары автомобиль–дата",
                  ],
                  [
                    "Дни движения ГЛОНАСС",
                    a.movementDays,
                    `От ${payload.state.settings.movement_threshold} км за сутки`,
                  ],
                  [
                    "Часы заявок ТТ",
                    a.hours,
                    "Длительность заявок; не моточасы",
                    false,
                  ],
                ].map(([l, v, t, integer = true]) => (
                  <button
                    key={l}
                    title={t}
                    onClick={() =>
                      l === "Заявки"
                        ? details(l, a.rows.filter(M.isTrip))
                        : l === "Рабочие авто-дни ТТ"
                          ? daysDetails(
                              l,
                              a.days.filter((d) => d.status === "Работа"),
                            )
                          : setDrawer({ type: "telemetry", title: l })
                    }
                  >
                    <span>
                      {l}
                      <ArrowUpRight size={14} />
                    </span>
                    <strong><AnimatedMetric value={v} format={fmt} integer={integer} /></strong>
                    <small>{t}</small>
                  </button>
                ))}
              </div>
              <RevenueReview rows={a.rows} Section={Section} onSelect={details} />
              <div className="dashboard-grid lower">
                <Section
                  title="Клиенты"
                  subtitle="Доля выручки · количество заявок отдельно от рабочих дней"
                  action={subnav("clients", "Все клиенты")}
                >
                  <div className="client-bars">
                    {overviewClients.map((r, i) => (
                        <button
                          key={r.name}
                          onClick={() => details(r.name, r.rows)}
                        >
                          <span className="rank">
                            {String(i + 1).padStart(2, "0")}
                          </span>
                          <span className="bar-name">
                            <b>{r.name}</b>
                            <span className="bar-track">
                              <i
                                style={{
                                  width:
                                    Math.max(
                                      0,
                                      Math.min(
                                        100,
                                        M.percent(r.revenue, a.revenue) || 0,
                                      ),
                                    ) + "%",
                                }}
                              />
                            </span>
                          </span>
                          <span>
                            <b><AnimatedMetric value={r.revenue} format={money} /></b>
                            <small>
                              <AnimatedMetric value={M.percent(r.revenue, a.revenue)} format={pct} /> ·{" "}
                              <AnimatedMetric value={r.trips} format={fmt} integer /> заявок
                            </small>
                          </span>
                        </button>
                      ))}
                  </div>
                  {!a.rows.length && <Empty />}
                </Section>
                <Section
                  title="Требует внимания"
                  subtitle="Отклонение — основание для проверки"
                  action={subnav("control", "Открыть реестр")}
                >
                  <div className="attention-total">
                    <span>
                      <ShieldCheck size={22} />
                    </span>
                    <strong><AnimatedMetric value={openSignals} format={fmt} integer /></strong>
                    <small>
                      сигналов
                      <br />
                      ожидают решения
                    </small>
                  </div>
                  {[...issuesByKind]
                    .slice(0, 4)
                    .map(([kind, kindIssues]) => (
                      <button
                        className="attention-row"
                        key={kind}
                        onClick={() => {
                          setDrawer({
                            type: "issues",
                            title: kind,
                            issues: kindIssues,
                          });
                        }}
                      >
                        <span>{kind}</span>
                        <b><AnimatedMetric value={kindIssues.length} format={fmt} integer /></b>
                        <ChevronRight size={14} />
                      </button>
                    ))}
                  {!issues.length && (
                    <p>В доступных данных сигналы не обнаружены.</p>
                  )}
                </Section>
              </div>
              <InfoNote>
                Показатели основаны на доступных записях. Километраж ТТ,
                отдельная оплата водителей и точная сверка интервалов требуют
                подтверждённых данных источников.
              </InfoNote>
            </>
          )}
          {rankPages.includes(page) && (
            <>
              <div className="dashboard-grid">
                <Section
                  title={
                    page === "clients"
                      ? "Выручка по клиентам"
                      : page === "drivers"
                        ? "Рейтинг водителей"
                        : "Рейтинг автомобилей"
                  }
                  subtitle="Нажмите строку для проверки исходных заявок"
                  action={
                    <SelectMenu ariaLabel="Показатель рейтинга" value={rankMetric} onChange={(e) => setRankMetric(e.target.value)} options={[
                      { value: "revenue", label: "По выручке" },
                      { value: "balance", label: "По результату" },
                      { value: "days", label: "По рабочим дням" },
                      { value: "average", label: "По среднему чеку" },
                    ]} />
                  }
                >
                  <div className="ranking">
                    {[...groupRows]
                      .sort(
                        (a, b) =>
                          (b[rankMetric] ?? -Infinity) -
                          (a[rankMetric] ?? -Infinity),
                      )
                      .slice(0, 7)
                      .map((r, i) => (
                        <button
                          key={r.name}
                          onClick={() => details(r.name, r.rows)}
                        >
                          <span className="rank">{i + 1}</span>
                          <span>
                            <b>{r.name}</b>
                            <small>
                              {r.carrier || (
                                <>
                                  <AnimatedMetric value={r.trips} format={fmt} integer /> заявок ·{" "}
                                  <AnimatedMetric value={r.days} format={fmt} integer /> рабочих дней
                                </>
                              )}
                            </small>
                          </span>
                          <strong>
                            <AnimatedMetric
                              key={rankMetric}
                              value={r[rankMetric]}
                              format={rankMetric === "days" ? fmt : money}
                              integer={rankMetric === "days"}
                            />
                          </strong>
                          <ArrowUpRight size={16} />
                        </button>
                      ))}
                  </div>
                </Section>
                {page === "drivers" ? (
                  <Section
                    title="Структура начислений"
                    subtitle="Категории ТТ · выплата по записи"
                  >
                    <CategoryBreakdown rows={a.rows} onSelect={details} />
                    <InfoNote>
                      В текущем импорте WorkerSum — выплата исполнителю.
                      Отдельная зарплата водителя не подтверждена и не
                      вычитается повторно.
                    </InfoNote>
                  </Section>
                ) : (
                  statusPanel
                )}
              </div>
              <FinanceGroups p={p} a={a} onSelect={details} />
              {page === "drivers" && (
                <InfoNote>
                  Рабочие дни водителя считаются по назначениям. Два автомобиля
                  в один день дают водителю один рабочий день. Суточный пробег
                  машины не приписывается водителю.
                </InfoNote>
              )}
              {page === "fleet" && <Opportunity a={a} />}
              <Section
                title={active[1] + " · подробная статистика"}
                subtitle="Маржинальный результат без ГСМ и прочих затрат"
              >
                <DataTable
                  rows={groupRows}
                  columns={groupCols(groupKey === "vehicle")}
                  title={active[1]}
                  onRow={(r) => details(r.name, r.rows)}
                />
              </Section>
            </>
          )}
          {page === "compare" && (
            <>
              <div className="comparison-toolbar">
                <SlidingTabs
                  className="segments"
                  items={[["objects", "Объекты за период"], ["periods", "Динамика по периодам"]]}
                  value={compareMode}
                  onChange={setCompareMode}
                />
                <SelectMenu ariaLabel="Группировка сравнения" value={compareBy} onChange={(e) => setCompareBy(e.target.value)} options={[
                  { value: "vehicle", label: "Автомобили" },
                  { value: "driver", label: "Водители" },
                  { value: "carrier", label: "Исполнители" },
                  { value: "client", label: "Клиенты" },
                  { value: "type", label: "Типы транспорта" },
                ]} />
              </div>
              <Section
                title={
                  compareMode === "objects"
                    ? "Сравнение выручки и выплат"
                    : "Динамика выручки и выплат"
                }
                subtitle={
                  compareMode === "objects"
                    ? "Первые 12 по выручке · полный список в таблице ниже"
                    : "Выбранные объекты вместе · каждый месяц периода"
                }
                action={<LegendRow />}
              >
                <MoneyChart
                  bar
                  data={
                    compareMode === "objects" ? comparisonRows.slice(0, 12) : comparisonRows
                  }
                  onSelect={(r) => details(r.name, r.rows)}
                />
              </Section>
              <InfoNote>
                Для сопоставимого рейтинга выберите один тип транспорта.
                Изменения KPI рассчитаны относительно {M.previousPeriod(...reportPeriod).map(date).join(" — ")}.
                При нулевой базе процент не рассчитывается.
              </InfoNote>
              <Section title="Числа для сравнения">
                <DataTable
                  title="Сравнение"
                  rows={comparisonRows}
                  columns={groupCols(
                    compareMode === "objects" && compareBy === "vehicle",
                  )}
                  onRow={(r) => details(r.name, r.rows)}
                />
              </Section>
            </>
          )}
          {page === "calendar" && (
            <>
              <div className="comparison-toolbar">
                <SlidingTabs
                  className="segments"
                  items={[["vehicle", "Автомобили"], ["driver", "Водители"]]}
                  value={calMode}
                  onChange={setCalMode}
                />
                <div className="inline">
                  <B
                    aria-label="Предыдущий месяц"
                    icon={<ChevronLeft size={16} />}
                    onClick={() =>
                      setPeriod(M.periodFor(M.addDays(period[0], -1), "month"))
                    }
                  />
                  <input
                    aria-label="Месяц календаря"
                    type="month"
                    value={period[0].slice(0, 7)}
                    onInput={(e) => {
                      if (M.validDay(e.currentTarget.value + "-01"))
                        setPeriod(
                          M.periodFor(e.currentTarget.value + "-01", "month"),
                        );
                    }}
                    onChange={(e) => {
                      if (e.target.value)
                        setPeriod(M.periodFor(e.target.value + "-01", "month"));
                    }}
                  />
                  <B
                    aria-label="Следующий месяц"
                    icon={<ChevronRight size={16} />}
                    onClick={() =>
                      setPeriod(
                        M.periodFor(
                          M.addDays(M.periodFor(period[0], "month")[1], 1),
                          "month",
                        ),
                      )
                    }
                  />
                </div>
              </div>
              <Calendar
                p={p}
                filters={reportFilters}
                period={reportPeriod}
                mode={calMode}
                onDay={(d) =>
                  setDrawer({
                    type: "day",
                    title: `${d.name} · ${date(d.date)}`,
                    day: d,
                  })
                }
              />
              <InfoNote>
                «Не заполнено» определяется автоматически. «Без заявки» задаётся
                вручную. Работа имеет приоритет; ремонт и другие события видны
                внутри ячейки и не удваивают рабочие дни.
              </InfoNote>
            </>
          )}
          {page === "planner" && (
            <PlannerPage
              p={p}
              period={reportPeriod}
              filters={reportFilters}
              user={user}
              onOpen={(row = null) =>
                setDrawer({
                  type: "plan",
                  title: row ? "Изменить назначение" : "Назначить маршрут",
                  row,
                })
              }
            />
          )}
          {page === "control" && (
            <>
              <div className="control-summary">
                <Card pad="large">
                  <span>Всего сигналов</span>
                  <strong><AnimatedMetric value={issues.length} format={fmt} integer /></strong>
                </Card>
                <Card pad="large">
                  <span>Ожидают решения</span>
                  <strong><AnimatedMetric value={openSignals} format={fmt} integer /></strong>
                </Card>
                <Card pad="large">
                  <span>Качество справочников и заявок</span>
                  <strong><AnimatedMetric value={q.length} format={fmt} integer /></strong>
                </Card>
                <Card pad="large">
                  <span>Порог движения</span>
                  <strong>
                    <AnimatedMetric value={payload.state.settings.movement_threshold} format={fmt} />
                    <small> км / сутки</small>
                  </strong>
                </Card>
              </div>
              <div className="comparison-toolbar">
                <SlidingTabs
                  className="segments"
                  items={[["signals", "Реестр отклонений"], ["quality", "Качество данных"]]}
                  value={controlTab}
                  onChange={setControlTab}
                />
                <Multi
                  {...multiProps("review")}
                  label="Статус проверки"
                  items={M.REVIEW_STATES}
                  value={reviewFilter}
                  onChange={setReviewFilter}
                />
              </div>
              <Section
                title={
                  controlTab === "signals"
                    ? "Очередь проверки"
                    : "Ошибки и неполные записи"
                }
                subtitle={
                  controlTab === "signals"
                    ? "Откройте сигнал, укажите решение и оставьте комментарий"
                    : "Все записи справочников; фильтры аналитики здесь не применяются"
                }
              >
                {controlTab === "signals" ? (
                  <IssueTable
                    issues={issues.filter((i) =>
                      M.selected(
                        reviewFilter,
                        payload.state.reviews[i.id]?.status || "Не проверено",
                      ),
                    )}
                    reviews={payload.state.reviews}
                    onRow={(r) =>
                      setDrawer({ type: "review", title: r.kind, issue: r })
                    }
                  />
                ) : (
                  <DataTable
                    rows={q}
                    title="Качество"
                    columns={[
                      { key: "name", label: "Запись" },
                      { key: "kind", label: "Что проверить" },
                    ]}
                  />
                )}
              </Section>
              <InfoNote>
                Перепробег рассчитывается только для сопоставимых интервалов.
                Суточный ГЛОНАСС рядом с километражом части суток не доказывает
                отклонение. При отсутствии точного интервала сигнал перепробега
                не формируется.
              </InfoNote>
            </>
          )}
          {page === "fuel" && (
            <FuelPage
              a={a}
              p={p}
              filters={reportFilters}
              settings={payload.state.settings}
              user={user}
              save={save}
              details={setDrawer}
              demo={payload.demo}
              onRefresh={refresh}
            />
          )}
          {page === "routes" && <RoutesPage p={p} />}
          {page === "data" && (
            <SourceDataPage
              p={p}
              fuel={fuel}
              period={reportPeriod}
              filters={reportFilters}
              onTrips={(title, rows) => details(title, rows)}
            />
          )}
          {page === "directories" && (
            <Directories
              p={p}
              user={user}
              refresh={refresh}
              onChoose={(kind, name) => {
                setFilters({ ...M.emptyFilters(), [kind]: [name] });
                go(kind === "drivers" ? "drivers" : "fleet");
              }}
            />
          )}
          {page === "connections" && (
            <ConnectionsPage
              user={user}
              period={reportPeriod}
              disabled={livePreview || !!payload.demo || !!payload.local_preview}
              livePreview={livePreview}
              demo={!!payload.demo}
              onRefresh={refresh}
            />
          )}
          {page === "settings" && (
            <Settings
              settings={payload.state.settings}
              save={save}
              user={user}
            />
          )}
          {page === "users" && user.role === "admin" && (
            <UsersPage p={p} user={user} onRename={(name) => setPayload((current) => ({ ...current, user: { ...current.user, name } }))} />
          )}
          </div>
          </ScrollRowsContext.Provider>
          )}
          </div>
          <footer className="page-footer">
            <span>
              CharterStats ·{" "}
              {livePreview
                ? "Локальный просмотр · данные рабочего API"
                : payload.demo
                ? "Демонстрационные данные · подключения к провайдерам отключены"
                : payload.local_preview
                  ? "Локальный предпросмотр · синхронизация отключена"
                  : "Аналитика по доступным данным"}
            </span>
            <button onClick={() => go("data")}>
              Исходные данные <ArrowRight size={12} />
            </button>
          </footer>
          </div>
        </main>
      </div>
      {drawer && (
        <Drawer
          title={drawer.title}
          size={["trips", "days", "telemetry", "fuel"].includes(drawer.type) ? "wide" : "compact"}
          onClose={() => setDrawer(null)}
        >
          {drawer.type === "trips" && (
            <>
              <InfoNote>
                Финансовые суммы учтены по дате начала заявки. Пробег заявки не
                распределяется по дням. «—» означает отсутствие данных.
              </InfoNote>
              <DataTable
                title="Исходные заявки"
                rows={drawer.rows}
                columns={tripCols}
              />
              <button
                className="text-link"
                onClick={() => {
                  setDrawer(null);
                  go("data");
                }}
              >
                Открыть исходные данные <ArrowRight size={14} />
              </button>
            </>
          )}
          {drawer.type === "days" && (
            <DataTable
              title="Даты статусов"
              rows={drawer.days}
              columns={[
                { key: "date", label: "Дата" },
                { key: "vehicle", label: "Автомобиль", vehicle: true },
                { key: "driver", label: "Водитель" },
                { key: "status", label: "Основной статус" },
                {
                  key: "events",
                  label: "События",
                  render: (r) =>
                    r.events.map((e) => e.reason).join(", ") || "—",
                },
              ]}
              onRow={(d) => {
                setCalMode("vehicle");
                setDrawer({
                  type: "day",
                  title: `${d.name} · ${date(d.date)}`,
                  day: d,
                });
              }}
            />
          )}
          {drawer.type === "day" && (
            <DayDetail
              day={drawer.day}
              events={workspace.statuses.filter((row) =>
                row.kind === calMode && row.entity === drawer.day.name && row.date === drawer.day.date
              )}
              onDelete={({ id, revision, delete_token }) =>
                changeStatus(`manual/${encodeURIComponent(id)}`, "DELETE", { revision, delete_token })
              }
              user={user}
              reasons={workspace.directories.reasons}
              onSave={saveStatus}
            />
          )}
          {drawer.type === "issues" && (
            <IssueTable
              issues={drawer.issues}
              reviews={payload.state.reviews}
              onRow={(r) =>
                setDrawer({ type: "review", title: r.kind, issue: r })
              }
            />
          )}
          {drawer.type === "review" && (
            <Review
              issue={drawer.issue}
              value={payload.state.reviews[drawer.issue.id]}
              user={user}
              onSave={async (r) => {
                await save({ kind: "review", review: r });
                setDrawer(null);
              }}
            />
          )}
          {drawer.type === "telemetry" && (
            <>
              <InfoNote>
                Данные относятся к автомобилю за сутки. Моточасы, движение,
                стоянки и часы заявки имеют разные определения.
              </InfoNote>
              <DataTable
                title="Спутниковые данные"
                rows={a.satellite}
                columns={[
                  { key: "date", label: "Дата" },
                  { key: "vehicle", label: "Автомобиль", vehicle: true },
                  col("km", "Пробег, км", fmtSatelliteKm),
                  col("engine_hours", "Моточасы, ч"),
                  col("movement_hours", "Движение, ч"),
                  col("stop_hours", "Стоянки, ч"),
                  col("hours", "Интервал, ч"),
                  { key: "source", label: "Источник" },
                ]}
              />
            </>
          )}
          {drawer.type === "fuel" && (
            <DataTable title="Заправки" rows={drawer.rows} columns={fuelCols} />
          )}
          {drawer.type === "plan" && (
            <PlanForm
              p={p}
              row={drawer.row}
              onSaved={async () => {
                await refresh();
                setDrawer(null);
              }}
            />
          )}
        </Drawer>
      )}
      </div>
    </VehicleMapContext.Provider>
  );
}
function CategoryBreakdown({ rows, onSelect }) {
  const cats = [...new Set(rows.map(M.category))].map((name) => ({
    name,
    rows: rows.filter((r) => M.category(r) === name),
  }));
  const total = M.sum(rows, "payout");
  return (
    <div className="category-list">
      {cats.map((c) => {
        const value = M.sum(c.rows, "payout");
        return (
          <button key={c.name} onClick={() => onSelect(c.name, c.rows)}>
            <span>{c.name}</span>
            <b><AnimatedMetric value={value} format={money} /></b>
            <small><AnimatedMetric value={M.percent(value, total)} format={pct} /></small>
          </button>
        );
      })}
    </div>
  );
}
function Calendar({ p, filters, period, mode, onDay }) {
  const [search, setSearch] = useState(""),
    days = useMemo(
      () => M.calendarRows(p, filters, ...period, mode),
      [p, filters, period, mode],
    );
  const { names, index } = useMemo(() => {
    const names = new Set();
    const index = new Map();
    for (const day of days) {
      names.add(day.name);
      index.set(day.name + "|" + day.date, day);
    }
    return { names: [...names], index };
  }, [days]);
  const query = search.toLowerCase();
  const matches = useMemo(() => query ? names.filter((name) => name.toLowerCase().includes(query)) : names, [names, query]);
  const dates = useMemo(() => M.daysBetween(...period).map((day) => ({
    day,
    weekday: weekday.format(new Date(day + "T12:00:00Z")),
  })), [period]);
  const selection = useMemo(() => ({ mode, search }), [mode, search]);
  const [visible, sentinel] = useScrollRows(matches.length, selection, CALENDAR_BATCH_SIZE, !search ? "Календарь " + mode : null);
  const renderRows = useCallback((start, end) =>
    matches.slice(start, end).map((name) => (
      <tr key={name}>
        <td>
          <strong>{name}</strong>
          <small>
            {
              (mode === "vehicle" ? p.vehicleMap : p.driverMap).get(
                name,
              )?.carrier
            }
          </small>
        </td>
        {dates.map(({ day: date }) => {
          const d = index.get(name + "|" + date);
          return (
            <td key={date}>
              {d && (
                <button
                  className="calendar-cell"
                  style={{
                    "--status": M.STATUS_COLORS[d.status] || "#82939d",
                  }}
                  title={`${date} · ${d.status}${d.events.length ? " · " + d.events.map((s) => M.statusName(s.reason)).join(", ") : ""}`}
                  aria-label={`${name} ${date} ${d.status}`}
                  onClick={() => onDay(d)}
                >
                  {d.status === "Работа" ? d.trips.length : M.calendarMark(d.status)}
                  {d.events.length > 0 && d.other.length > 0 && (
                    <small>+</small>
                  )}
                </button>
              )}
            </td>
          );
        })}
      </tr>
    )), [matches, mode, p, dates, index, onDay]);
  return (
    <Section
      title="Календарь занятости"
      subtitle="Нажмите на день, чтобы открыть заявки и изменить статусы"
    >
      <div className="calendar-legend">
        {Object.entries(M.STATUS_COLORS)
          .map(([s, c]) => (
            <span key={s}>
              <i style={{ background: c }} />
              {s === "Работа" ? s : `${M.calendarMark(s)} · ${s}`}
            </span>
          ))}
      </div>
      <div className="table-tools">
        <div className="search-input">
          <Search size={16} />
          <input
            aria-label="Поиск в календаре"
            placeholder={
              mode === "vehicle" ? "Найти автомобиль" : "Найти водителя"
            }
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span className="muted">
          <AnimatedMetric key={mode} value={matches.length} format={fmt} integer />{" "}
          {mode === "vehicle" ? "автомобилей" : "водителей"}
        </span>
      </div>
      <div className="table-scroll calendar-scroll">
        <table className="calendar-table">
          <thead>
            <tr>
              <th>{mode === "vehicle" ? "Автомобиль" : "Водитель"}</th>
              {dates.map(({ day, weekday }) => (
                <th key={day} title={day}>
                  {day.slice(8)}
                  <small>{weekday}</small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <RowBatches visible={visible} batchSize={CALENDAR_BATCH_SIZE} render={renderRows} />
          </tbody>
        </table>
      </div>
      {!matches.length && <Empty />}
      {visible < matches.length && <ScrollRows sentinel={sentinel} />}
    </Section>
  );
}
function DayDetail({ day, events, user, reasons, onSave, onDelete }) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [mode, setMode] = useState("day");
  const [from, setFrom] = useState(day.date);
  const [to, setTo] = useState(day.date);
  const [dates, setDates] = useState([day.date]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const selectedDates = mode === "range" ? M.daysBetween(from, to)
    : mode === "dates" ? [...new Set(dates)] : [day.date];
  const validDates = selectedDates.length > 0 && selectedDates.length <= 367
    && selectedDates.every(M.validDay);
  const status = M.calendarStatus(day.trips.length, { ...day, events });
  const editable = user.role !== "viewer";
  async function apply(action, success) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      setMessage(success);
    } catch (error) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="day-summary">
        <Badge tone={status === "Не заполнено" ? "warning" : "success"}>
          {status}
        </Badge>
        <span>
          <AnimatedMetric value={day.trips.length} format={fmt} integer /> заявок ·{" "}
          <AnimatedMetric value={M.extraEventCount({ ...day, events })} format={fmt} integer /> дополнительных записей
        </span>
      </div>
      {day.trips.length > 0 && (
        <DataTable title="Заявки дня" rows={day.trips} columns={tripCols} />
      )}
      {day.other.length > day.trips.length && (
        <InfoNote>
          Есть работа вне текущих фильтров. День не считается незаполненным.
        </InfoNote>
      )}
      <h3>Установленные статусы</h3>
      {events.length ? (
        events.map((e) => (
          <div className="event" key={e.id || e.reason}>
            <b>{M.statusName(e.reason)}</b>
            <p>{e.note || "Без комментария"}</p>
            {editable && e.delete_token && (
              <B size="small" disabled={busy} aria-label={`Удалить статус «${M.statusName(e.reason)}»`}
                onClick={() => apply(() => onDelete(e), "Статус удалён.")}>
                <span>Удалить</span>
              </B>
            )}
          </div>
        ))
      ) : (
        <p className="muted">Ручных статусов пока нет.</p>
      )}
      {editable && (
        <form
          className="form calendar-status-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy || !reason || !validDates) return;
            void apply(
              () => onSave(day, selectedDates, reason, note),
              `Статус сохранён. Дат: ${selectedDates.length}.`,
            );
          }}
        >
          <h3>{events.length ? "Изменить статус" : "Установить статус"}</h3>
          <label>
            Даты
            <select aria-label="Даты" value={mode} onChange={(event) => setMode(event.target.value)} disabled={busy}>
              <option value="day">Выбранный день</option>
              <option value="range">Период</option>
              <option value="dates">Отдельные даты</option>
            </select>
          </label>
          {mode === "range" && (
            <div className="status-date-fields">
              <label>Дата с<input type="date" required value={from} onChange={(event) => setFrom(event.target.value)} disabled={busy} /></label>
              <label>Дата по<input type="date" required min={from} value={to} onChange={(event) => setTo(event.target.value)} disabled={busy} /></label>
            </div>
          )}
          {mode === "dates" && (
            <>
              {dates.map((value, index) => (
                <div className="status-date-fields" key={index}>
                  <label>Дата {index + 1}<input type="date" required value={value} disabled={busy}
                    onChange={(event) => setDates(dates.map((date, i) => i === index ? event.target.value : date))} /></label>
                  <B size="small" disabled={busy || dates.length === 1} aria-label={`Убрать дату ${index + 1}`}
                    onClick={() => setDates(dates.filter((_, i) => i !== index))}><span>Убрать</span></B>
                </div>
              ))}
              <B disabled={busy || dates.length >= 367} onClick={() => setDates([...dates, ""])}>
                <span>Добавить дату</span>
              </B>
            </>
          )}
          {!validDates && <p className="muted">Укажите от 1 до 367 дат в правильном порядке для периода.</p>}
          <label>
            Причина
            <SelectMenu required disabled={busy} ariaLabel="Причина" value={reason} onChange={(e) => setReason(e.target.value)} options={[
              { value: "", label: "Выберите причину" },
              ...reasons
                .filter(
                  (r, i, all) =>
                    !r.archived &&
                    all.findIndex(
                      (x) =>
                        !x.archived &&
                        M.statusName(x.name) === M.statusName(r.name),
                    ) === i,
                )
                .map((r) => ({ value: r.name, label: M.statusName(r.name) })),
            ]} />
          </label>
          <label>
            Комментарий
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={3}
              disabled={busy}
            />
          </label>
          <p className="muted">Сохранение заменит ручные статусы на выбранных датах. Заявки сохранятся.</p>
          <B variant="primary" type="submit" disabled={busy || !reason || !validDates}>
            <span>{busy ? "Сохранение…" : "Сохранить статус"}</span>
          </B>
        </form>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </>
  );
}
async function downloadIssues(rows, vehicles) {
  const values = rows.map((row) => [
    row.date, row.vehicle, vehicles.get(row.vehicle)?.carrier ?? row.carrier ?? "",
    row.driver ?? "", row.kind, row.detail, row.status, row.comment,
  ]);
  const blob = await api("charter/deviations/export", {
    method: "POST",
    body: JSON.stringify(values),
    asBlob: true,
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "Отклонения.xlsx";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function IssueTable({ issues, reviews, onRow }) {
  return (
    <DataTable
      rows={issues.map((r) => ({
        ...r,
        status: reviews[r.id]?.status || "Не проверено",
        comment: reviews[r.id]?.comment ?? "",
      }))}
      title="Отклонения"
      downloadRows={downloadIssues}
      columns={[
        { key: "date", label: "Дата" },
        { key: "vehicle", label: "Автомобиль", vehicle: true },
        { key: "kind", label: "Сигнал" },
        { key: "detail", label: "Основание" },
        {
          key: "status",
          label: "Проверка",
          render: (r) => (
            <Badge
              tone={
                r.status === "Нарушение"
                  ? "danger"
                  : r.status === "Исправлено" || r.status === "Обосновано"
                    ? "success"
                    : r.status === "В работе"
                      ? "accent"
                      : "warning"
              }
            >
              {r.status}
            </Badge>
          ),
        },
      ]}
      onRow={onRow}
    />
  );
}
function Review({ issue, value, user, onSave }) {
  const [status, setStatus] = useState(value?.status || "Не проверено"),
    [comment, setComment] = useState(value?.comment || ""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const can =
    user.role === "admin" ||
    (user.role === "logist" && user.vehicles.includes(issue.vehicle));
  return (
    <>
      <div className="detail-facts">
        <span>
          Дата<b>{issue.date}</b>
        </span>
        <span>
          Автомобиль<b>{issue.vehicle}</b>
        </span>
        <span>
          Водитель<b>{issue.driver || "Не назначен"}</b>
        </span>
        <span>
          Исполнитель<b>{issue.carrier || "Не установлен"}</b>
        </span>
      </div>
      <InfoNote>{issue.detail}</InfoNote>
      <form
        className="form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await onSave({ ...issue, status, comment });
          } catch (e) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Результат проверки
          <SelectMenu disabled={!can} ariaLabel="Результат проверки" value={status} onChange={(e) => setStatus(e.target.value)} options={M.REVIEW_STATES} />
        </label>
        <label>
          Комментарий ответственного
          <textarea
            disabled={!can}
            rows={4}
            value={comment}
            maxLength={2000}
            onChange={(e) => setComment(e.target.value)}
            placeholder={issue.kind === M.UNFILLED_DAY_ISSUE
              ? "Укажите, почему день остался незаполненным"
              : "Что проверили и чем объясняется отклонение"}
            required={["Обосновано", "Нарушение", "Исправлено"].includes(
              status,
            )}
          />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {can && (
          <B variant="primary" type="submit" disabled={busy}>
            <span>Сохранить решение</span>
          </B>
        )}
      </form>
      <h3>История проверки</h3>
      {value?.history?.length ? (
        [...value.history].reverse().map((r, i) => (
          <div className="history-item" key={i}>
            <Badge>{r.status}</Badge>
            <p>{r.comment || "Без комментария"}</p>
            <small>
              {r.author} · {stamp(r.at)} МСК
            </small>
          </div>
        ))
      ) : (
        <p className="muted">Решений ещё нет.</p>
      )}
    </>
  );
}
const fuelCols = [
  { key: "date", label: "Дата" },
  {
    key: "vehicle",
    label: "Автомобиль",
    vehicle: true,
  },
  { key: "provider", label: "Источник" },
  { key: "card", label: "Карта" },
  { key: "product", label: "Топливо" },
  col("liters", "Объём, л"),
  col("amount", "Сумма", money),
  { key: "driver", label: "Водитель" },
  { key: "allocation", label: "Привязка к машине" },
];
function RosneftDriverCards({ onRefresh }) {
  const [data, setData] = useState(null);
  const [number, setNumber] = useState("");
  const [driver, setDriver] = useState("");
  const [date, setDate] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api("rosneft/driver-assignments", { signal: controller.signal })
      .then(setData)
      .catch((error) => {
        if (!controller.signal.aborted) setMessage(error.message);
      });
    return () => controller.abort();
  }, []);

  const selected = data?.cards.find((row) => row.card === number);
  const last = selected?.history.at(-1);
  const start = date || (last?.start > data?.today ? last.start : data?.today) || "";
  async function assign(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const updated = await api("rosneft/driver-assignments", {
        method: "PUT",
        body: JSON.stringify({ card: number, driver_id: driver, start, revision: last?.id ?? null }),
      });
      setData(updated);
      setMessage("Водитель привязан к карте.");
      await onRefresh();
    } catch (error) {
      setMessage(error.message);
      if (error.status === 409) {
        await api("rosneft/driver-assignments").then(setData).catch(() => {});
      }
    } finally {
      setBusy(false);
    }
  }
  const cards = (data?.cards || []).map(({ card, note, history }) => {
    const latest = history.at(-1);
    return {
      card, note,
      driver: latest?.driver || "",
      start: latest?.start,
      status: !latest?.driver ? "Требует выбора" :
        latest.source === "auto" ? "По ФИО" : "Вручную",
    };
  });
  return (
    <Section title="Карты Роснефти и водители"
      subtitle="После обновления Роснефти однозначное совпадение по ФИО действует со следующего дня. Ручной выбор имеет приоритет.">
      {data && cards.length > 0 && (
        <form className="inline-form" onSubmit={assign}>
          <label>Карта
            <select aria-label="Карта" className="rosneft-assignment-select" required value={number} disabled={busy} onChange={(e) => {
              setNumber(e.target.value);
              setDriver("");
              setDate("");
              setMessage("");
            }}>
              <option value="">Выберите карту</option>
              {cards.map((row) => <option key={row.card} value={row.card}>{row.card}</option>)}
            </select>
          </label>
          <label>Водитель
            <select aria-label="Водитель" className="rosneft-assignment-select" required value={driver} disabled={busy} onChange={(e) => setDriver(e.target.value)}>
              <option value="">Выберите водителя</option>
              {data.drivers.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </label>
          <label>Действует с
            <input required type="date" value={start} min={last?.start} disabled={busy}
              onChange={(e) => setDate(e.target.value)} />
          </label>
          <B variant="primary" type="submit" disabled={busy || !selected || !driver}>Привязать</B>
        </form>
      )}
      <div role="status">{message || (!data ? "Загрузка карт…" : "")}</div>
      {data && (cards.length ? <DataTable title="Карты Роснефти" rows={cards} columns={[
        { key: "card", label: "Карта" },
        { key: "note", label: "Примечание Роснефти" },
        { key: "driver", label: "Водитель" },
        { key: "start", label: "Действует с" },
        { key: "status", label: "Назначение" },
      ]} /> : <InfoNote>Список карт появится после обновления Роснефти.</InfoNote>)}
      {selected?.history.length > 0 && (
        <DataTable title="История выбранной карты" rows={selected.history.map((row) => ({ ...row, status: row.source === "manual" ? "Вручную" : row.driver ? "По ФИО" : "Автопривязка снята" }))} columns={[
          { key: "start", label: "Действует с" },
          { key: "driver", label: "Водитель" },
          { key: "status", label: "Назначение" },
        ]} />
      )}
    </Section>
  );
}

function FuelPage({ demo, onRefresh, ...props }) {
  return (
    <>
      {props.user.role === "admin" && !demo && <RosneftDriverCards onRefresh={onRefresh} />}
      <FuelReport {...props} />
    </>
  );
}

function FuelReport({ a, p, filters, settings, user, save, details }) {
  const [car, setCar] = useState(""),
    [norm, setNorm] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  if (user.role !== "admin")
    return (
      <InfoNote>
        Исходные операции топливных карт доступны руководителю. Для просмотра
        обратитесь к ответственному сотруднику.
      </InfoNote>
    );
  const scoped =
    filters.clients.length || filters.statuses.length;
  if (scoped)
    return (
      <InfoNote>
        Заправки не связаны однозначно с выбранными клиентами или статусами. Очистите эти фильтры, чтобы увидеть статистику по
        автомобилям.
      </InfoNote>
    );
  if (filters.drivers.length)
    return (
      <Section title="Операции по выбранным водителям">
        <DataTable title="Заправки" columns={fuelCols}
          rows={a.fuel.filter((row) => filters.drivers.includes(row.driver))} />
      </Section>
    );
  const purchases = a.fuel.filter((r) => r.liters !== null),
    liters = M.sum(purchases, "liters"),
    amount = M.sum(purchases, "amount");
  const rows = [
    ...new Set([
      ...purchases.map((r) => r.vehicle || M.UNKNOWN),
      ...a.satellite.map((r) => r.vehicle),
    ]),
  ].map((name) => {
    const ops = purchases.filter((r) => (r.vehicle || M.UNKNOWN) === name),
      sat = a.satellite.filter((r) => r.vehicle === name),
      km = M.knownSum(sat, "km"),
      norm = settings.fuel_norms[name] ?? null,
      expected = km !== null && norm !== null ? (km * norm) / 100 : null,
      fuel = M.sum(ops, "liters");
    return {
      name,
      km,
      norm,
      expected,
      liters: fuel,
      amount: M.sum(ops, "amount"),
      difference: fuel !== null && expected !== null ? fuel - expected : null,
      actual: M.knownSum(sat, "fuel_liters"),
      ops,
    };
  });
  return (
    <>
      <div className="kpi-grid">
        <KPI
          label="Расходы по картам"
          raw={amount}
          format={money}
          sub="С учётом возвратов · доступные операции"
          onClick={() =>
            details({
              type: "fuel",
              title: "Операции топливных карт",
              rows: a.fuel,
            })
          }
        />
        <KPI
          label="Заправлено"
          raw={liters}
          format={litersText}
          sub="Объём заправок, не фактический расход"
          onClick={() =>
            details({ type: "fuel", title: "Заправки", rows: purchases })
          }
        />
        <KPI
          label="Средняя цена литра"
          raw={M.ratio(amount, liters)}
          format={money}
          sub="Стоимость / заправленный объём"
          onClick={() =>
            details({ type: "fuel", title: "Расчёт цены", rows: purchases })
          }
        />
        <KPI
          label="Без привязки к авто"
          raw={a.fuel.filter((r) => !r.vehicle).length}
          integer
          sub="Требуется историческая привязка карты"
          onClick={() =>
            details({
              type: "fuel",
              title: "Операции без привязки",
              rows: a.fuel.filter((r) => !r.vehicle),
            })
          }
        />
      </div>
      <Section
        title="Заправки и норматив"
        subtitle="Норма × пробег ГЛОНАСС / 100 · только по доступным показаниям"
      >
        <DataTable
          title="ГСМ по автомобилям"
          rows={rows}
          columns={[
            { key: "name", label: "Автомобиль", vehicle: true },
            col("km", "ГЛОНАСС, км"),
            col("norm", "Норма, л/100 км"),
            col("expected", "Норматив, л"),
            col("liters", "Заправлено, л"),
            col("difference", "Разница, л"),
            col("actual", "Расход датчика, л"),
            col("amount", "Стоимость", money),
          ]}
          onRow={(r) => details({ type: "fuel", title: r.name, rows: r.ops })}
        />
      </Section>
      <InfoNote>
        Разница между заправками и нормативом не доказывает перерасход. Нужны
        остатки в баке или надёжный датчик. Отсутствующие сутки ГЛОНАСС не
        заменяются нулями; норматив относится только к доступному пробегу.
      </InfoNote>
      <Section
        title="Норма автомобиля"
        subtitle="Норма сохраняется в настройках приложения"
      >
        <form
          className="inline-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await save({
                kind: "settings",
                settings: {
                  ...settings,
                  fuel_norms: { ...settings.fuel_norms, [car]: Number(norm) },
                },
              });
              setMessage("Норма сохранена");
            } catch (e) {
              setMessage(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Автомобиль
            <SelectMenu required ariaLabel="Автомобиль" value={car} onChange={(e) => {
                setCar(e.target.value);
                setNorm(settings.fuel_norms[e.target.value] || "");
              }} options={[{ value: "", label: "Выберите" }, ...p.vehicles.map((v) => ({ value: v.name, label: v.name }))]} />
          </label>
          <label>
            Литров на 100 км
            <input
              type="number"
              required
              min="0.1"
              max="200"
              step="0.1"
              value={norm}
              onChange={(e) => setNorm(e.target.value)}
            />
          </label>
          <B variant="primary" type="submit" disabled={busy}>
            Сохранить
          </B>
          <span role="status">{message}</span>
        </form>
      </Section>
      <Section
        title="Операции топливных карт"
        subtitle="Время и АЗС не передаются в текущей нормализованной сводке; доступны в исходных данных"
      >
        <DataTable title="Заправки" rows={a.fuel} columns={fuelCols} />
        <a className="text-link" href="/data/fuelcards">
          История привязок карт <ExternalLink size={14} />
        </a>
      </Section>
    </>
  );
}
function RoutesPage({ p }) {
  const routes = p.routes.filter((r) => !r.archived && !r.inactive_route),
    [first, setFirst] = useState(routes[0]?.id || ""),
    [second, setSecond] = useState(routes[1]?.id || ""),
    a = routes.find((r) => r.id === first),
    b = routes.find((r) => r.id === second),
    r = a && b ? M.swapResult(a, b) : null;
  return (
    <>
      <InfoNote tone="warm">
        Предварительный сценарий по тарифам маршрутов. Доступность автомобилей и
        водителей, расположение, нулевой пробег, ограничения клиента и стоимость
        ГСМ требуют проверки перед назначением.
      </InfoNote>
      <div className="scenario-intro">
        <div>
          <span className="eyebrow">Два маршрута · одна экономика</span>
          <h2>
            Есть ли смысл поменять
            <br />
            назначения местами?
          </h2>
          <p>
            Сравните результат пары заказов. Выручка остаётся той же; меняются
            выплаты собственному водителю и привлечённому исполнителю.
          </p>
        </div>
        <Route size={68} strokeWidth={1} />
      </div>
      <div className="dashboard-grid equal">
        <Section
          title="Маршрут А"
          subtitle="В базовом сценарии — собственный автомобиль"
        >
          <SelectMenu ariaLabel="Маршрут А" value={first} onChange={(e) => setFirst(e.target.value)} options={routes.map((r) => ({ value: r.id, label: r.name || r.id }))} />
          {a && <RouteFacts route={a} />}
        </Section>
        <Section
          title="Маршрут Б"
          subtitle="В базовом сценарии — привлечённый исполнитель"
        >
          <SelectMenu ariaLabel="Маршрут Б" value={second} onChange={(e) => setSecond(e.target.value)} options={routes.map((r) => ({ value: r.id, label: r.name || r.id }))} />
          {b && <RouteFacts route={b} />}
        </Section>
      </div>
      {r && first !== second ? (
        <>
          <div className="scenario-results">
            <Card pad="large">
              <span>Базовый результат</span>
              <strong><AnimatedMetric value={r.current} format={money} /></strong>
              <small>Свой на А · привлечённый на Б</small>
            </Card>
            <div className="scenario-arrow">
              <ArrowRight />
            </div>
            <Card pad="large">
              <span>Альтернативный результат</span>
              <strong><AnimatedMetric value={r.alternative} format={money} /></strong>
              <small>Свой на Б · привлечённый на А</small>
            </Card>
            <Card pad="large" className="scenario-gain">
              <span>Изменение результата</span>
              <strong>
                <AnimatedMetric value={r.value} format={signedMoney} />
              </strong>
              <small>
                {r.percent === null
                  ? "Нет базы для сравнения"
                  : <><AnimatedMetric value={r.percent} format={pct} /> к текущему варианту</>}
              </small>
            </Card>
          </div>
          <Section title="Что проверить перед перестановкой">
            <div className="detail-facts">
              <span>
                Категория маршрута А<b>{a.group || "Не определена"}</b>
              </span>
              <span>
                Категория маршрута Б<b>{b.group || "Не определена"}</b>
              </span>
              <span>
                Суммарная выручка<b><AnimatedMetric value={r.revenue} format={money} /></b>
              </span>
              <span>
                Дополнительный нулевой пробег<b>Нет данных</b>
              </span>
              <span>
                Изменение рабочего времени<b>Нет данных</b>
              </span>
              <span>
                Автомобиль и водитель свободны<b>Не подтверждено</b>
              </span>
            </div>
            <InfoNote>
              {r.value === null
                ? "Недостаточно тарифов для расчёта."
                : r.value > 0
                  ? "Перестановка может увеличить результат по указанным выплатам. Это предварительный расчёт, не готовое назначение."
                  : "По указанным выплатам перестановка не улучшает совокупный результат."}
            </InfoNote>
          </Section>
        </>
      ) : (
        <Empty>Выберите два разных маршрута</Empty>
      )}
    </>
  );
}
function RouteFacts({ route: r }) {
  return (
    <div className="route-facts">
      <span>
        Выручка<b><AnimatedMetric value={r.revenue} format={money} /></b>
      </span>
      <span>
        Собственному водителю<b><AnimatedMetric value={r.payout} format={money} /></b>
      </span>
      <span>
        Привлечённому исполнителю<b><AnimatedMetric value={r.partner_payout} format={money} /></b>
      </span>
      <span>
        Пробег маршрута<b><AnimatedMetric value={r.km} format={fmt} /> км</b>
      </span>
      <span>
        Время маршрута<b><AnimatedMetric value={r.hours} format={fmt} /> ч</b>
      </span>
    </div>
  );
}
function Directories({ p, onChoose, user, refresh }) {
  const [search, setSearch] = useState("");
  const carriers = [
    ...new Set([
      ...p.vehicles.map((r) => r.carrier),
      ...p.drivers.map((r) => r.carrier),
    ]),
  ].sort((a, b) =>
    a === M.UNKNOWN ? 1 : b === M.UNKNOWN ? -1 : a.localeCompare(b, "ru"),
  );
  return (
    <>
      <InfoNote>
        Принадлежность взята из текущего справочника, а не из исполнителя
        отдельной заявки. Неустановленные связи показаны отдельно. Импорт
        справочников ТТ и их актуальность требуют отдельной проверки источника.
      </InfoNote>
      <div className="search-input directory-search">
        <Search size={16} />
        <input
          aria-label="Поиск в справочниках"
          placeholder="Исполнитель, автомобиль или водитель"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {carriers.map((carrier) => {
        const matches = (n) =>
            !search ||
            n.toLowerCase().includes(search.toLowerCase()) ||
            carrier.toLowerCase().includes(search.toLowerCase()),
          cars = p.vehicles.filter(
            (v) => v.carrier === carrier && matches(v.name),
          ),
          drivers = p.drivers.filter(
            (v) => v.carrier === carrier && matches(v.name),
          );
        if (!cars.length && !drivers.length) return null;
        return (
          <Card pad="large" key={carrier} className="directory-group">
            <details
              open={!!search || carrier === M.UNKNOWN || carriers.length < 5}
            >
              <summary>
                <Building2 size={20} />
                <span>
                  <strong>
                    {carrier === M.UNKNOWN
                      ? "Принадлежность не установлена"
                      : carrier}
                  </strong>
                  <small>
                    {M.ownership(carrier)} · <AnimatedMetric value={cars.length} format={fmt} integer /> автомобилей ·{" "}
                    <AnimatedMetric value={drivers.length} format={fmt} integer /> водителей
                  </small>
                </span>
                <ChevronDown size={18} />
              </summary>
              <div className="directory-columns">
                <div>
                  <h3>Автомобили</h3>
                  {[...new Set(cars.map((v) => v.transport_type))].map(
                    (type) => (
                      <details key={type} open>
                        <summary>
                          {type === M.UNKNOWN ? "Тип не установлен" : type}
                          <span>
                            {
                              cars.filter((v) => v.transport_type === type)
                                .length
                            }
                          </span>
                        </summary>
                        {cars
                          .filter((v) => v.transport_type === type)
                          .map((v) => (
                            <button
                              key={v.name}
                              onClick={() => onChoose("vehicles", v.name)}
                            >
                              <Truck size={15} />
                              {v.name}
                              <small>{v.brand}</small>
                              <ArrowUpRight size={14} />
                            </button>
                          ))}
                      </details>
                    ),
                  )}
                </div>
                <div>
                  <h3>Водители</h3>
                  {drivers.map((d) => (
                    <button
                      key={d.name}
                      onClick={() => onChoose("drivers", d.name)}
                    >
                      <Users size={15} />
                      {d.name}
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                </div>
              </div>
            </details>
          </Card>
        );
      })}
      {user.role === "admin" && <AssignmentEditor p={p} refresh={refresh} />}
      <a className="text-link" href="/data/directories">
        Редактировать справочники <ExternalLink size={14} />
      </a>
    </>
  );
}
function PlannerPage({ p, period, filters, user, onOpen }) {
  const rows = (p.plans || [])
    .filter(
      (r) =>
        r.date >= period[0] &&
        r.date <= period[1] &&
        M.selected(filters.vehicles, r.vehicle) &&
        M.selected(filters.drivers, r.driver) &&
        M.selected(filters.carriers, r.carrier || M.UNKNOWN),
    )
    .sort((a, b) => a.date.localeCompare(b.date));
  const included = rows.filter(
    (r) => ["scheduled", "unassigned"].includes(r.state) && !r.duplicate_review,
  );
  return (
    <>
      <div className="planner-actions">
        <InfoNote>
          Отменённые назначения, записи без маршрута и спорные повторы не входят
          в плановые итоги. Тариф фиксируется на дату назначения.
        </InfoNote>
        {user.role !== "viewer" && (
          <B
            className="planner-primary-action"
            variant="primary"
            icon={<Plus size={15} />}
            onClick={() => onOpen()}
          >
            Назначить маршрут
          </B>
        )}
      </div>
      <div className="control-summary">
        {[
          ["Назначений", included.length, fmt, true],
          ["Выручка, план", M.knownSum(included, "revenue"), money],
          ["Выплаты, план", M.knownSum(included, "payout"), money],
          ["Пробег, план", M.knownSum(included, "km"), (v) => fmt(v) + " км"],
        ].map(([label, value, format, integer]) => (
          <Card pad="large" key={label}>
            <span>{label}</span>
            <strong><AnimatedMetric value={value} format={format} integer={integer} /></strong>
          </Card>
        ))}
      </div>
      <Section
        title="Назначения водитель → автомобиль → маршрут"
        subtitle="План сохраняется отдельно от фактических заявок ТрансТрейда"
      >
        <DataTable
          rows={rows}
          title="Планировщик"
          onRow={user.role === "viewer" ? undefined : onOpen}
          columns={[
            { key: "date", label: "Дата" },
            { key: "vehicle", label: "Автомобиль", vehicle: true },
            { key: "driver", label: "Водитель" },
            { key: "route", label: "Маршрут" },
            {
              key: "state",
              label: "Состояние",
              render: (r) =>
                ({
                  scheduled: "Назначен",
                  unassigned: "Не назначен ресурс / водитель",
                  no_route: "Нет маршрута",
                  cancelled: "Отменён",
                  review: "Требует проверки",
                })[r.state] || r.state || "—",
            },
            { key: "slot", label: "Смена" },
            col("revenue", "Выручка", money),
            col("payout", "Выплата", money),
            col("km", "Км"),
            col("hours", "Часы"),
          ]}
        />
      </Section>
    </>
  );
}

function PlanForm({ p, row, onSaved }) {
  const editing = !!row;
  const today = new Date().toLocaleDateString("sv-SE");
  const [dateValue, setDateValue] = useState(row?.date || today);
  const [routeId, setRouteId] = useState(row?.route_id || "");
  const [vehicleId, setVehicleId] = useState(row?.vehicle_id || "");
  const [driverId, setDriverId] = useState(row?.driver_id || "");
  const [quote, setQuote] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const active = (kind) =>
    (p.directories[kind] || []).filter(
      (r) => !r.archived && !r.merged_into && !r.placeholder,
    );
  useEffect(() => {
    if (!routeId || !dateValue) {
      setQuote("");
      return;
    }
    let current = true;
    api("tariffs/quote?" + new URLSearchParams({ route: routeId, date: dateValue }))
      .then((q) => {
        if (current)
          setQuote(
            "Тариф на дату: " + money(q.revenue) +
              " · водителю " + money(q.payout) +
              " · партнёру " + money(q.partner_payout) +
              " · " + fmt(q.km) + " км · " + fmt(q.hours) + " ч",
          );
      })
      .catch((e) => current && setQuote(e.message));
    return () => {
      current = false;
    };
  }, [routeId, dateValue]);
  return (
    <form
      className="form plan-form"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setMessage("");
        try {
          const body = Object.fromEntries(new FormData(event.currentTarget));
          body.state = "scheduled";
          if (!editing)
            body.weekdays = [...event.currentTarget.querySelectorAll('[name="weekdays"]:checked')].map(
              (input) => Number(input.value),
            );
          if (editing) body.revision = row.revision;
          await api(editing ? "records/" + (row.record_id || row.id) : "manual/plans", {
            method: editing ? "PUT" : "POST",
            body: JSON.stringify(body),
          });
          await onSaved();
        } catch (e) {
          setMessage(e.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Дата
        <input
          name="date"
          type="date"
          required
          value={dateValue}
          onChange={(e) => setDateValue(e.target.value)}
        />
      </label>
      {!editing && (
        <label>
          По
          <input name="end_date" type="date" required defaultValue={dateValue} />
        </label>
      )}
      <label>
        Автомобиль / ресурс
        <SelectMenu name="vehicle_id" ariaLabel="Автомобиль / ресурс" value={vehicleId} onChange={(event) => setVehicleId(event.target.value)} options={[
          { value: "", label: "Не выбран" },
          ...active("vehicles").map((item) => ({ value: item.id, label: item.name })),
        ]} />
      </label>
      <label>
        Водитель
        <SelectMenu name="driver_id" ariaLabel="Водитель" value={driverId} onChange={(event) => setDriverId(event.target.value)} options={[
          { value: "", label: "Не выбран" },
          ...active("drivers").map((item) => ({ value: item.id, label: item.name })),
        ]} />
      </label>
      <label>
        Маршрут
        <SelectMenu name="route_id" ariaLabel="Маршрут" value={routeId} onChange={(event) => setRouteId(event.target.value)} options={[
          { value: "", label: "Не выбран" },
          ...active("routes").map((item) => ({ value: item.id, label: item.name })),
        ]} />
      </label>
      <label>
        Номер смены / рейса
        <input name="slot" defaultValue={row?.slot || ""} maxLength={100} />
      </label>
      <label>
        Комментарий
        <textarea name="note" defaultValue={row?.note || ""} rows={3} maxLength={1000} />
      </label>
      {!editing && (
        <fieldset className="weekday-field">
          <legend>Дни недели</legend>
          {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((label, index) => (
            <label key={label}>
              <input type="checkbox" name="weekdays" value={index} defaultChecked />
              {label}
            </label>
          ))}
        </fieldset>
      )}
      {quote && <InfoNote>{quote}</InfoNote>}
      {message && <p className="error" role="alert">{message}</p>}
      <div className="form-actions">
        {editing && (
          <B
            type="button"
            disabled={busy}
            onClick={async () => {
              if (!window.confirm("Убрать назначение? Действие сохранится в журнале.")) return;
              setBusy(true);
              try {
                await api("manual/" + (row.record_id || row.id), {
                  method: "DELETE",
                  body: JSON.stringify({
                    revision: row.revision,
                    delete_token: row.delete_token,
                  }),
                });
                await onSaved();
              } catch (e) {
                setMessage(e.message);
                setBusy(false);
              }
            }}
          >
            Убрать назначение
          </B>
        )}
        <button className="plan-submit" type="submit" disabled={busy}>
          {editing ? "Сохранить" : "Создать назначения"}
        </button>
      </div>
    </form>
  );
}

function SourceDataPage({ p, fuel, period, filters, onTrips }) {
  const [tab, setTab] = useState("orders");
  const inPeriod = (row) => row.date >= period[0] && row.date <= period[1];
  const trips = p.trips.filter((r) => inPeriod(r) && M.matches(r, filters, p));
  const plans = (p.plans || []).filter(
    (r) =>
      inPeriod(r) &&
      M.selected(filters.vehicles, r.vehicle) &&
      M.selected(filters.drivers, r.driver),
  );
  const statuses = (p.statuses || []).filter((r) => inPeriod(r));
  const satellite = (p.satellite || []).filter(
    (r) => inPeriod(r) && M.selected(filters.vehicles, r.vehicle),
  );
  const fuelRows = (fuel || []).filter(
    (r) => inPeriod(r) && M.selected(filters.vehicles, r.vehicle),
  );
  return (
    <>
      <SlidingTabs
        className="source-tabs"
        items={[
          ["orders", "Заявки"],
          ["plans", "Назначения"],
          ["statuses", "Статусы"],
          ["satellite", "Спутник"],
          ["fuel", "Топливо"],
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "orders" && (
        <Section title="Заявки ТрансТрейд и ручные записи" subtitle="Фактическая работа; исходные записи не заменяются планом">
          <DataTable
            rows={trips}
            columns={tripCols}
            title="Заявки"
            onRow={(r) => onTrips("Заявка " + r.id, [r])}
          />
        </Section>
      )}
      {tab === "plans" && (
        <Section title="Исходные назначения" subtitle="Сохранённый план до сопоставления с фактом">
          <DataTable
            rows={plans}
            title="Назначения"
            columns={[
              { key: "date", label: "Дата" },
              { key: "vehicle", label: "Автомобиль", vehicle: true },
              { key: "driver", label: "Водитель" },
              { key: "route", label: "Маршрут" },
              { key: "state", label: "Состояние" },
              col("revenue", "Выручка", money),
              col("payout", "Выплата", money),
            ]}
          />
        </Section>
      )}
      {tab === "statuses" && (
        <Section title="Статусы и простои" subtitle="Ручные причины по автомобилям и водителям">
          <DataTable
            rows={statuses}
            title="Статусы"
            columns={[
              { key: "date", label: "Дата" },
              { key: "kind", label: "Объект" },
              { key: "entity", label: "Наименование" },
              { key: "reason", label: "Причина" },
              { key: "note", label: "Комментарий" },
            ]}
          />
        </Section>
      )}
      {tab === "satellite" && (
        <Section title="Показания ГЛОНАССсофт" subtitle="Суточные значения автомобиля; не километраж отдельной заявки">
          <DataTable
            rows={satellite}
            title="Спутниковые данные"
            columns={[
              { key: "date", label: "Дата" },
              { key: "vehicle", label: "Автомобиль", vehicle: true },
              col("km", "Пробег, км", fmtSatelliteKm),
              col("engine_hours", "Моточасы"),
              col("movement_hours", "Движение"),
              col("stop_hours", "Стоянки"),
              { key: "source", label: "Источник" },
            ]}
          />
        </Section>
      )}
      {tab === "fuel" && (
        <Section title="Топливные операции" subtitle="Операции доступны руководителю; карты связываются с автомобилем по датам">
          <DataTable rows={fuelRows} title="Топливо" columns={fuelCols} />
        </Section>
      )}
    </>
  );
}

function ConnectionsPage({ user, period, disabled, demo, livePreview, onRefresh }) {
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const load = () =>
    api("connections").then(setRows).catch((e) => setMessage(e.message));
  useEffect(() => {
    load();
  }, []);
  const sync = async (id) => {
    setBusy(id);
    setMessage("");
    try {
      const body = id === "monitoring" ? {} : { from: period[0], to: period[1] };
      await api(id + "/sync", { method: "POST", body: JSON.stringify(body) });
      await Promise.all([load(), onRefresh()]);
      setMessage("Данные обновлены");
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy("");
    }
  };
  return (
    <>
      {disabled && (
        <InfoNote tone="warning">
          {demo
            ? "В демонстрационном режиме подключения отключены."
            : livePreview
              ? "Показаны сохранённые статусы рабочего API. Проверка и обновление доступны на рабочем сайте."
              : "Это локальная копия. Проверка сети и обновление данных доступны на рабочем сайте. Даты в карточках относятся к сохранённым данным."}
        </InfoNote>
      )}
      {!disabled && <div className="connections-head">
        <p className="muted">
          Проверка сети не отправляет логины и пароли и не доказывает доступ к данным.
        </p>
        {user.role === "admin" && (
          <B
            disabled={!!busy}
            onClick={async () => {
              setBusy("check");
              try {
                const result = await api("connections/check", { method: "POST", body: "{}" });
                setRows(result);
                setMessage("Проверка подключений завершена");
              } catch (e) {
                setMessage(e.message);
              } finally {
                setBusy("");
              }
            }}
          >
            Проверить подключения
          </B>
        )}
      </div>}
      <div className="connection-grid">
        {rows.map((row) => (
          <Card pad="large" className="connection-card" key={row.id}>
            <div className="connection-title">
              <div>
                <h2>{row.name}</h2>
                {!disabled && <small>{row.checked_at || row.authorization_checked_at || "Не проверено"}</small>}
              </div>
              <Badge tone={!disabled && /подключ|готов/i.test(row.status) ? "success" : "neutral"}>
                {disabled
                  ? demo
                    ? "Демонстрация"
                    : row.authorization_checked_at
                      ? "Есть сохранённые сведения"
                      : "Нет сведений о проверке"
                  : row.status}
              </Badge>
            </div>
            <p>{disabled
              ? demo
                ? "Подключение к поставщику в этом режиме отключено."
                : row.authorization_checked_at
                  ? `Последняя сохранённая отметка: ${row.authorization_checked_at}. Текущий доступ здесь не проверяется.`
                : "Нет отметки о проверке доступа."
              : row.detail}</p>
            <div className="connection-actions">
              {row.url && (
                <a href={row.url} target="_blank" rel="noreferrer">
                  Документация <ExternalLink size={13} />
                </a>
              )}
              {!disabled && user.role === "admin" && (
                <B
                  disabled={!!busy}
                  onClick={() => sync(row.id)}
                  icon={<RefreshCw size={14} className={busy === row.id ? "spin" : ""} />}
                >
                  Обновить данные
                </B>
              )}
            </div>
          </Card>
        ))}
      </div>
      {message && <p className="success-message" role="status">{message}</p>}
    </>
  );
}

const userRoles = [
  { value: "logist", label: "Логист" },
  { value: "viewer", label: "Наблюдатель" },
  { value: "admin", label: "Руководитель" },
];
const auditActions = {
  "create statuses": "Добавление статусов",
  "replace statuses": "Изменение статусов",
  "create plans": "Добавление назначений",
  "edit record": "Изменение записи",
  "delete record": "Удаление записи",
  "add user": "Добавление пользователя",
  "edit user": "Редактирование пользователя",
  "delete user": "Удаление пользователя",
  "assign rosneft driver": "Назначение водителя на карту Роснефти",
};
const auditTime = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  dateStyle: "short",
  timeStyle: "medium",
});

function assignedVehicles(account) {
  try {
    const names = JSON.parse(account?.vehicles || "[]");
    return Array.isArray(names) ? names : [];
  } catch {
    return [];
  }
}

function UserForm({ account, ownAccount, vehicleNames, onSaved }) {
  const [role, setRole] = useState(account?.role ?? "logist");
  const [vehicles, setVehicles] = useState(() => assignedVehicles(account));
  const [vehicleMenu, setVehicleMenu] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const dismissVehicleMenu = useCallback(() => setVehicleMenu(false), []);
  const vehicleId = account ? "edit-user-vehicles" : "user-vehicles";
  const choices = [...new Set([...vehicleNames, ...assignedVehicles(account)])];

  return (
    <form
      className={account ? "form user-edit-form" : "inline-form user-form"}
      onSubmit={async (event) => {
        event.preventDefault();
        if (saving) return;
        const form = event.currentTarget;
        const body = { ...Object.fromEntries(new FormData(form)), vehicles };
        setSaving(true);
        setError("");
        try {
          await api(account ? `users/${account.id}` : "users", {
            method: account ? "PUT" : "POST",
            body: JSON.stringify(body),
          });
          if (!account) {
            form.reset();
            setRole("logist");
            setVehicles([]);
            setVehicleMenu(false);
          }
          await onSaved(body.name.trim());
        } catch (e) {
          setError(e.message);
        } finally {
          setSaving(false);
        }
      }}
    >
      <label>Имя<input name="name" required defaultValue={account?.name} /></label>
      <label>
        {account ? "Новый пароль" : "Пароль"}
        <input name="password" type="password" minLength={12} required={!account} autoComplete="new-password" />
        {account && <small>Оставьте поле пустым, чтобы сохранить текущий пароль</small>}
      </label>
      <div className="user-form-field">
        <span>Роль</span>
        <SelectMenu name="role" ariaLabel="Роль" value={role} onChange={(e) => setRole(e.target.value)} options={userRoles} disabled={ownAccount} />
      </div>
      <div className="user-form-field user-vehicle-field">
        <label htmlFor={vehicleId}>Автомобили</label>
        <Multi id={vehicleId} label="Выберите автомобили" items={choices} value={vehicles} onChange={setVehicles} open={vehicleMenu} onToggle={(_, next) => setVehicleMenu(next)} onDismiss={dismissVehicleMenu} fitViewport />
      </div>
      <B variant="primary" type="submit" disabled={saving}>
        {account ? (saving ? "Сохраняем…" : "Сохранить изменения") : (saving ? "Добавляем…" : "Добавить пользователя")}
      </B>
      {error && <span role="alert" className="error">{error}</span>}
    </form>
  );
}

function UsersPage({ p, user, onRename }) {
  const [users, setUsers] = useState(null);
  const [audit, setAudit] = useState(null);
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const vehicleNames = p.vehicles.map(({ name }) => name);
  const accounts = useMemo(() => users?.map((r) => ({
    ...r,
    role_label: userRoles.find(({ value }) => value === r.role)?.label ?? r.role,
  })) ?? null, [users]);
  const events = useMemo(() => {
    const names = new Map(users?.map((r) => [r.id, r.name]));
    return audit?.map((r) => ({
      ...r,
      actor: names.get(r.user_id) ?? r.user_id,
      action_label: auditActions[r.action] ?? r.action,
    })) ?? null;
  }, [audit, users]);
  const load = () =>
    Promise.all([api("users"), api("audit")])
      .then(([userRows, auditRows]) => {
        setUsers(userRows);
        setAudit(auditRows);
      })
      .catch((e) => {
        setUsers((rows) => rows ?? []);
        setAudit((rows) => rows ?? []);
        setMessage(e.message);
      });
  useEffect(() => {
    load();
  }, []);
  async function remove(account) {
    if (deleting || !window.confirm(`Удалить пользователя «${account.name}»?`)) return;
    setDeleting(account.id);
    setMessage("");
    try {
      await api(`users/${account.id}`, { method: "DELETE" });
      setMessage("Пользователь удалён");
      await load();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setDeleting(null);
    }
  }
  return (
    <>
      <Section title="Пользователи и роли">
        <DataTable
          rows={accounts}
          title="Пользователи"
          columns={[
            { key: "name", label: "Имя" },
            { key: "role_label", label: "Роль" },
            {
              key: "vehicles",
              label: "Назначенные автомобили",
              render: (r) => r.role === "admin" ? "Все автомобили" : assignedVehicles(r).join(", ") || "Не назначены",
            },
            {
              key: "actions",
              label: "Действия",
              sortable: false,
              render: (account) => (
                <div className="user-row-actions">
                  <B size="small" aria-label={`Редактировать пользователя «${account.name}»`} disabled={deleting !== null} onClick={() => setEditing(account)}>
                    Редактировать
                  </B>
                  {account.id !== user.id && (
                    <B size="small" aria-label={`Удалить пользователя «${account.name}»`} disabled={deleting !== null} onClick={() => remove(account)}>
                      {deleting === account.id ? "Удаляем…" : "Удалить"}
                    </B>
                  )}
                </div>
              ),
            },
          ]}
        />
        <UserForm vehicleNames={vehicleNames} onSaved={async () => {
          setMessage("Пользователь добавлен");
          await load();
        }} />
        {message && <span role="status">{message}</span>}
      </Section>
      {editing && (
        <Drawer title="Редактирование пользователя" size="compact" onClose={() => setEditing(null)}>
          <UserForm account={editing} ownAccount={editing.id === user.id} vehicleNames={vehicleNames} onSaved={async (name) => {
            if (editing.id === user.id) onRename(name);
            setEditing(null);
            setMessage("Изменения сохранены");
            await load();
          }} />
        </Drawer>
      )}
      <Section title="Журнал действий" subtitle="Последние 100 событий">
        <DataTable
          rows={events}
          title="Журнал"
          columns={[
            {
              key: "at", label: "Время (МСК)", render: (r) => {
                const timestamp = Date.parse(r.at);
                return Number.isFinite(timestamp)
                  ? <time dateTime={r.at}>{auditTime.format(timestamp)}</time>
                  : (r.at || "—");
              },
            },
            { key: "actor", label: "Пользователь" },
            { key: "action_label", label: "Действие" },
            { key: "detail", label: "Детали" },
          ]}
        />
      </Section>
    </>
  );
}

function Settings({ settings, save, user }) {
  const [draft, setDraft] = useState(settings),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <>
      <Section
        title="Пороги контроля"
        subtitle="Пробег сохраняется независимо от порога движения"
      >
        <form
          className="form settings-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await save({ kind: "settings", settings: draft });
              setMessage("Настройки сохранены");
            } catch (e) {
              setMessage(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {[
            ["movement_threshold", "День движения, км", 1000],
            ["excess_km", "Допустимый перепробег, км", 10000],
            ["excess_percent", "Допустимый перепробег, % от ТТ", 1000],
          ].map(([key, label, max]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                value={draft[key]}
                required
                min={0}
                max={max}
                step="0.1"
                disabled={user.role !== "admin"}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    [key]: e.target.value === "" ? "" : Number(e.target.value),
                  })
                }
              />
            </label>
          ))}
          <p className="muted">
            Сигнал перепробега: превышены оба порога. При нулевом ТТ применяется
            только порог в километрах. Сравнение требует одинакового интервала.
          </p>
          {user.role === "admin" && (
            <B type="submit" variant="primary" disabled={busy}>
              Сохранить настройки
            </B>
          )}
          <span role="status">{message}</span>
        </form>
      </Section>
      <Section title="Определения показателей">
        <div className="definitions">
          {[
            [
              "Заявки",
              "Уникальные записи рейсов, без начислений, премий, ПРР и удержаний.",
            ],
            [
              "Рабочий день",
              "Автомобиль и календарная дата с рейсом; несколько рейсов не удваивают день. Для водителя — уникальная дата назначения.",
            ],
            [
              "Финансовый период",
              "Сохранено действующее правило по дате начала заявки. Переходящий рейс даёт рабочие дни в обоих периодах, деньги и километраж учитываются один раз.",
            ],
            [
              "Маржинальный результат",
              "Выручка минус выплаты по заявкам. Без ГСМ, ремонта, лизинга и амортизации. Отдельная выплата водителю не вычитается повторно.",
            ],
            [
              "ГЛОНАСС",
              "Суточные показания автомобиля. Не являются точными показаниями за интервал отдельного рейса или за смену конкретного водителя.",
            ],
            [
              "Отсутствующие данные",
              "Обозначены «—». Известная часть спутникового пробега подписана как доступные показания; неполные финансовые суммы не выдаются за итог.",
            ],
            [
              "Будущие расходы",
              "1С и ФинТабло не подключены. Текущий состав затрат не смешивается с расширенной экономикой.",
            ],
          ].map(([a, b]) => (
            <div key={a}>
              <h3>{a}</h3>
              <p>{b}</p>
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}
createRoot(document.getElementById("root")).render(<App />);
function TelemetrySummary({ a, onDetails }) {
  return (
    <Section
      title="Пробег и время"
      subtitle="Заявки ТТ и доступные суточные показания автомобиля"
      action={
        <button onClick={onDetails}>
          Показания <ArrowRight size={14} />
        </button>
      }
    >
      <div className="telemetry-summary">
        <div>
          <span>Пробег ТТ</span>
          <strong>
            <AnimatedMetric value={a.km} format={fmt} /> <small>км</small>
          </strong>
          <small>
            {a.km === null
              ? "Нет полного километража заявок"
              : "Один раз на заявку"}
          </small>
        </div>
        <div>
          <span>Пробег ГЛОНАСС</span>
          <strong>
            <AnimatedMetric value={a.sat_km} format={fmt} /> <small>км</small>
          </strong>
          <small>
            {a.satelliteScoped
              ? "Нет однозначной связи с выборкой"
              : <><AnimatedMetric value={a.sat_coverage} format={fmt} integer /> авто-дней с показаниями</>}
          </small>
        </div>
        <div>
          <span>Время ТТ</span>
          <strong>
            <AnimatedMetric value={a.hours} format={fmt} /> <small>ч</small>
          </strong>
          <small>Длительность заявок</small>
        </div>
        <div>
          <span>Моточасы ГЛОНАСС</span>
          <strong>
            <AnimatedMetric
              value={a.satelliteScoped ? null : M.knownSum(a.satellite, "engine_hours")}
              format={fmt}
            />{" "}
            <small>ч</small>
          </strong>
          <small>Зажигание, не время работы</small>
        </div>
      </div>
      <div className="section-foot">
        Отклонение: — · для точной разницы в км, часах и процентах нужны
        сопоставимые интервалы. Суточные показания не распределяются по заявкам.
      </div>
    </Section>
  );
}
function FinanceGroups({ p, a, onSelect }) {
  const kinds = ["Собственный парк", "Привлечённые", "Не установлено"];
  return (
    <Section
      title="Финансы по принадлежности"
      subtitle="Состав выплат сохранён как в источнике; без повторного вычитания зарплаты"
    >
      <div className="finance-groups">
        {kinds.map((kind) => {
          const rows = a.rows.filter(
              (r) =>
                (p.vehicleMap.get(r.vehicle)?.ownership || "Не установлено") ===
                kind,
            ),
            f = M.financial(rows);
          return (
            <div key={kind}>
              <h3>{kind}</h3>
              <button onClick={() => onSelect(kind, rows)}>
                <span>Выручка</span>
                <b><AnimatedMetric value={f.revenue} format={money} /></b>
              </button>
              <button onClick={() => onSelect(kind + " · выплаты", rows)}>
                <span>
                  {kind === "Собственный парк"
                    ? "Выплаты по заявкам"
                    : "Исполнителям"}
                </span>
                <b><AnimatedMetric value={f.payout} format={money} /></b>
              </button>
              <div>
                <span>Доля выплат</span>
                <b><AnimatedMetric value={f.payout_percent} format={pct} /></b>
              </div>
              <div>
                <span>Разница</span>
                <b><AnimatedMetric value={f.balance} format={money} /></b>
              </div>
              <div>
                <span>Доля разницы</span>
                <b><AnimatedMetric value={f.margin} format={pct} /></b>
              </div>
              {kind === "Собственный парк" && (
                <p>
                  Оплата водителю отдельно: <AnimatedMetric value={f.driver_payout} format={money} />.{" "}
                  {f.driver_payout === null
                    ? "Источник не подтверждает отдельное поле зарплаты."
                    : "Включена в выплаты; повторно не вычитается."}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}
function Opportunity({ a }) {
  const rows = useMemo(() => {
    const reasons = ["Без заявки", "Без водителя", "Ремонт / сервис"];
    const weekdayOf = (day) => new Date(day + "T12:00:00Z").getUTCDay();
    const idleByVehicle = new Map();
    for (const day of a.days) {
      if (!idleByVehicle.has(day.vehicle)) idleByVehicle.set(day.vehicle, new Map());
      if (!reasons.includes(day.status)) continue;
      const idle = idleByVehicle.get(day.vehicle);
      if (!idle.has(day.status)) idle.set(day.status, []);
      idle.get(day.status).push(day);
    }
    const revenueByVehicle = new Map();
    for (const trip of a.rows) {
      if (!idleByVehicle.get(trip.vehicle)?.size || !M.isTrip(trip)) continue;
      const [from, to] = M.tripSpan(trip);
      if (from !== to) continue;
      if (!revenueByVehicle.has(trip.vehicle)) revenueByVehicle.set(trip.vehicle, new Map());
      const byDay = revenueByVehicle.get(trip.vehicle);
      if (!byDay.has(trip.date)) byDay.set(trip.date, []);
      byDay.get(trip.date).push(trip);
    }
    const result = [];
    for (const [name, idle] of idleByVehicle) {
      if (!idle.size) continue;
      const sums = Array(7).fill(0);
      const counts = Array(7).fill(0);
      for (const [day, trips] of revenueByVehicle.get(name) || []) {
        const revenue = M.sum(trips, "revenue");
        if (revenue === null) continue;
        const weekday = weekdayOf(day);
        sums[weekday] += revenue;
        counts[weekday]++;
      }
      for (const reason of reasons) {
        const days = idle.get(reason);
        if (!days) continue;
        let estimate = 0;
        let covered = 0;
        for (const day of days) {
          const weekday = weekdayOf(day.date);
          if (!counts[weekday]) continue;
          estimate += sums[weekday] / counts[weekday];
          covered++;
        }
        result.push({ name, reason, days: days.length, covered, estimate: covered === days.length ? estimate : null });
      }
    }
    return result;
  }, [a]);
  return (
    <Section
      title="Упущенная выручка · оценка"
      subtitle="Средняя выручка того же автомобиля в тот же день недели × подтверждённые дни простоя"
    >
      <DataTable
        title="Оценка простоя"
        rows={rows}
        columns={[
          { key: "name", label: "Автомобиль", vehicle: true },
          { key: "reason", label: "Причина" },
          col("days", "Дни простоя", fmt, true),
          col("covered", "Дни с базой сравнения", fmt, true),
          col("estimate", "Оценка выручки", money),
        ]}
      />
      <InfoNote>
        Это сценарная оценка, а не финансовый убыток. Пустые дни, выходные и
        переходящие рейсы исключены из базы. Без сопоставимых рабочих дней
        оценка не рассчитывается.
      </InfoNote>
    </Section>
  );
}
function AssignmentEditor({ p, refresh }) {
  const [kind, setKind] = useState("vehicles"),
    [id, setId] = useState(""),
    [carrier, setCarrier] = useState(""),
    [type, setType] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const rows = (p.directories[kind] || []).filter(
    (r) =>
      !r.archived &&
      !r.merged_into &&
      (kind === "vehicles"
        ? !r.resource_type || r.resource_type === "vehicle"
        : !r.placeholder),
  );
  return (
    <Section
      title="Уточнить принадлежность"
      subtitle="Ручное подтверждение связи в текущем справочнике приложения"
    >
      <form
        className="inline-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = rows.find((r) => r.id === id);
          if (!r) return;
          setBusy(true);
          try {
            await api(`catalog/${kind}/${id}`, {
              method: "PUT",
              body: JSON.stringify({
                ...r,
                carrier_id: carrier,
                ...(kind === "vehicles" ? { transport_type_id: type } : {}),
              }),
            });
            setMessage("Связь сохранена");
            await refresh();
          } catch (e) {
            setMessage(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Справочник
          <SelectMenu ariaLabel="Справочник" value={kind} onChange={(e) => {
              setKind(e.target.value);
              setId("");
              setCarrier("");
              setType("");
            }} options={[{ value: "vehicles", label: "Автомобили" }, { value: "drivers", label: "Водители" }]} />
        </label>
        <label>
          Запись
          <SelectMenu required ariaLabel="Запись" value={id} onChange={(e) => {
              const r = rows.find((r) => r.id === e.target.value);
              setId(e.target.value);
              setCarrier(r?.carrier_id || "");
              setType(r?.transport_type_id || "");
            }} options={[{ value: "", label: "Выберите" }, ...rows.map((r) => ({ value: r.id, label: r.name }))]} />
        </label>
        <label>
          Исполнитель
          <SelectMenu ariaLabel="Исполнитель" value={carrier} onChange={(e) => setCarrier(e.target.value)} options={[
            { value: "", label: "Связь с исполнителем ТТ не установлена" },
            ...(p.directories.carriers || [])
              .filter((r) => !r.archived)
              .map((r) => ({ value: r.id, label: r.name })),
          ]} />
        </label>
        {kind === "vehicles" && (
          <label>
            Тип транспорта
            <SelectMenu ariaLabel="Тип транспорта" value={type} onChange={(e) => setType(e.target.value)} options={[
              { value: "", label: "Не установлен" },
              ...(p.directories.transport_types || [])
                .filter(
                  (r) =>
                    !r.archived && M.category({ type: r.name }) === "Вождение",
                )
                .map((r) => ({ value: r.id, label: r.name })),
            ]} />
          </label>
        )}
        <B type="submit" variant="primary" disabled={!id || busy}>
          Сохранить связь
        </B>
        <span role="status">{message}</span>
      </form>
    </Section>
  );
}
