import React from "react";
import { ChevronRight } from "lucide-react";
import { Card } from "./vendor/stageshow/parts/card";

const barHeights = [83, 71, 76, 63, 58, 68, 47, 51, 39, 43, 34, 28];

function ChartPlaceholder({ bar }) {
  return (
    <div className="skeleton-chart-lines" aria-hidden="true">
      {bar && <div className="skeleton-chart-bars">
        {barHeights.map((height, index) => (
          <div key={index} className="skeleton-chart-pair" style={{ "--bar-height": `${height}%` }}>
            <span />
            <span />
          </div>
        ))}
      </div>}
    </div>
  );
}

export function ChartSkeleton({ bar }) {
  return (
    <div className="chart chart-skeleton" role="status">
      <span className="loading-announcement">Загрузка графика…</span>
      <ChartPlaceholder bar={bar} />
    </div>
  );
}

function SkeletonRows({ shape, rows }) {
  const calendar = shape === "calendar";
  const columns = calendar ? 32 : shape === "table" ? 5 : 2;
  return (
    <div className="skeleton-rows">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index}>
          {Array.from({ length: columns }, (_, column) => (
            <span className={calendar && column > 0 ? "skeleton-line skeleton-calendar-cell" : "skeleton-line"} key={column} />
          ))}
        </div>
      ))}
    </div>
  );
}

function SkeletonFields({ count }) {
  return (
    <div className="skeleton-fields">
      {Array.from({ length: count }, (_, index) => <span className="skeleton-line" key={index} />)}
    </div>
  );
}

function SkeletonCard({ shape = "rows", rows = 5, fields = 0 }) {
  const metric = shape === "metric" || shape === "summary";
  return (
    <Card pad="large" className={`section skeleton-card skeleton-card--${shape}`}>
      <div className="skeleton-line skeleton-label" />
      {fields > 0 && <SkeletonFields count={fields} />}
      {metric ? (
        <>
          <div className="skeleton-line skeleton-value" />
          <div className="skeleton-line skeleton-caption" />
        </>
      ) : shape === "chart" || shape === "bar-chart" ? (
        <ChartPlaceholder bar={shape === "bar-chart"} />
      ) : rows > 0 && <SkeletonRows shape={shape} rows={rows} />}
    </Card>
  );
}

function SkeletonTabs({ className = "", count }) {
  return (
    <div className={`skeleton-tabs ${className}`}>
      {Array.from({ length: count }, (_, index) => <span className="skeleton-line" key={index} />)}
    </div>
  );
}

function SkeletonToolbar({ tabs = 2 }) {
  return (
    <div className="comparison-toolbar skeleton-toolbar">
      <SkeletonTabs count={tabs} />
      <span className="skeleton-line" />
    </div>
  );
}

function SkeletonMetrics({ compact = false }) {
  return (
    <div className={compact ? "control-summary" : "kpi-grid"}>
      {Array.from({ length: 4 }, (_, index) => <SkeletonCard key={index} shape={compact ? "summary" : "metric"} />)}
    </div>
  );
}

function ReportPlaceholderContent({ page }) {
  switch (page) {
    case "overview":
      return <>
        <SkeletonMetrics />
        <div className="dashboard-grid">
          <SkeletonCard shape="chart" />
          <SkeletonCard rows={5} />
        </div>
      </>;
    case "fleet":
    case "drivers":
    case "clients":
      return <>
        <div className="dashboard-grid">
          <SkeletonCard shape="ranking" rows={7} />
          <SkeletonCard rows={page === "drivers" ? 5 : 7} />
        </div>
        <SkeletonCard shape="table" rows={5} />
      </>;
    case "compare":
      return <>
        <SkeletonToolbar />
        <SkeletonCard shape="bar-chart" />
        <SkeletonCard shape="table" rows={5} />
      </>;
    case "calendar":
      return <>
        <SkeletonToolbar />
        <SkeletonCard shape="calendar" rows={7} fields={1} />
      </>;
    case "planner":
      return <>
        <SkeletonToolbar tabs={1} />
        <SkeletonMetrics compact />
        <SkeletonCard shape="table" rows={7} />
      </>;
    case "control":
      return <>
        <SkeletonMetrics compact />
        <SkeletonToolbar />
        <SkeletonCard shape="table" rows={7} />
      </>;
    case "fuel":
      return <>
        <SkeletonCard shape="table" fields={3} rows={5} />
        <SkeletonMetrics />
      </>;
    case "routes":
      return <>
        <div className="scenario-intro skeleton-scenario">
          <div>
            <span className="skeleton-line skeleton-label" />
            <span className="skeleton-line skeleton-value" />
            <span className="skeleton-line skeleton-caption" />
          </div>
        </div>
        <div className="dashboard-grid equal">
          <SkeletonCard rows={5} fields={1} />
          <SkeletonCard rows={5} fields={1} />
        </div>
      </>;
    case "data":
      return <>
        <SkeletonTabs className="source-tabs" count={5} />
        <SkeletonCard shape="table" rows={7} />
      </>;
    case "directories":
      return <>
        <SkeletonTabs className="catalog-tabs" count={4} />
        <SkeletonTabs className="catalog-subtabs" count={3} />
        <SkeletonCard shape="table" rows={7} />
      </>;
    case "connections":
      return <div className="connection-grid">
        {Array.from({ length: 4 }, (_, index) => <SkeletonCard key={index} rows={2} />)}
      </div>;
    case "settings":
      return <>
        <SkeletonCard shape="form" fields={3} rows={0} />
        <SkeletonCard rows={5} />
      </>;
    case "users":
      return <>
        <SkeletonCard shape="table" rows={4} />
        <SkeletonCard shape="table" rows={5} />
      </>;
    default:
      return <SkeletonCard shape="table" rows={7} />;
  }
}

export function ReportSkeleton({ page }) {
  return (
    <div className="report-skeleton" aria-hidden="true">
      <ReportPlaceholderContent page={page} />
    </div>
  );
}

export function WorkspaceSkeleton({ page, title, hint, filtered }) {
  return (
    <div className="workspace workspace-skeleton">
      <span className="loading-announcement" role="status">Загрузка рабочего пространства…</span>
      <aside className="sidebar" aria-hidden="true">
        <span className="wordmark">CharterStats<span> / </span></span>
        <div className="skeleton-nav">
          {Array.from({ length: 11 }, (_, index) => <div key={index} className="skeleton-line" />)}
        </div>
      </aside>
      <div className="main-wrap" aria-busy="true">
        <header className="topbar">
          <span className="topbar-context">Рабочее пространство <ChevronRight size={13} /> <b>{title}</b></span>
          <span className="topbar-brand wordmark">CharterStats<span> / </span></span>
          <div className="skeleton-line skeleton-refresh" aria-hidden="true" />
        </header>
        <main>
          <div className="page-heading">
            <div>
              <span className="eyebrow">CHARTER / ANALYTICS</span>
              <h1>{title}</h1>
              <p>{hint}</p>
            </div>
          </div>
          {filtered && (
            <div className="filters skeleton-filters" aria-hidden="true">
              <div className="filter-line">
                <span className="skeleton-line" />
                <span className="skeleton-line" />
                <span className="skeleton-line" />
                <span className="skeleton-line" />
              </div>
              <div className="skeleton-line skeleton-presets" />
            </div>
          )}
          <ReportSkeleton page={page} />
        </main>
      </div>
    </div>
  );
}
