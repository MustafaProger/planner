import React from "react";
import { ChevronRight } from "lucide-react";
import { Card } from "./vendor/stageshow/parts/card";

export function ChartSkeleton() {
  return (
    <div className="chart chart-skeleton" role="status">
      <span className="loading-announcement">Загрузка графика…</span>
      <div className="skeleton-chart-lines" aria-hidden="true" />
    </div>
  );
}

function SkeletonCard({ shape = "rows", rows = 5 }) {
  return (
    <Card pad="large" className={`section skeleton-card skeleton-card--${shape}`}>
      <div className="skeleton-line skeleton-label" />
      {shape === "metric" ? (
        <>
          <div className="skeleton-line skeleton-value" />
          <div className="skeleton-line skeleton-caption" />
        </>
      ) : shape === "chart" ? (
        <>
          <div className="skeleton-line skeleton-value" />
          <div className="skeleton-chart-lines" />
        </>
      ) : (
        <div className="skeleton-rows">
          {Array.from({ length: rows }, (_, index) => (
            <div className="skeleton-row" key={index}>
              <span className="skeleton-line" />
              <span className="skeleton-line" />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function ReportSkeleton({ page }) {
  const overview = page === "overview";
  const ranking = ["fleet", "drivers", "clients"].includes(page);
  const hasMetrics = overview || page === "control";
  return (
    <div className="report-skeleton" aria-hidden="true">
      {hasMetrics && (
        <div className="kpi-grid">
          {Array.from({ length: 4 }, (_, index) => <SkeletonCard key={index} shape="metric" />)}
        </div>
      )}
      {overview || ranking ? (
        <div className="dashboard-grid">
          <SkeletonCard shape={overview ? "chart" : "ranking"} rows={7} />
          <SkeletonCard rows={page === "drivers" ? 5 : 7} />
        </div>
      ) : (
        <SkeletonCard shape={page === "compare" ? "chart" : "rows"} rows={7} />
      )}
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
