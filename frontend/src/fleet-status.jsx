import React, { useLayoutEffect, useRef } from "react";
import { ChevronRight } from "lucide-react";
import { AnimatedMetric } from "./animated-metric.jsx";
import { Badge } from "./vendor/stageshow/controls/badge";
import { STATUS_COLORS, percent } from "./model";
import { REPORT_EASE_OUT, REPORT_MOTION_MS } from "./report-motion.js";
import "./report-data-motion.css";

const orderedStatuses = Object.keys(STATUS_COLORS);
const fleetMotionStyle = {
  "--fleet-status-duration": `${REPORT_MOTION_MS}ms`,
  "--fleet-status-easing": REPORT_EASE_OUT,
};

export function FleetStatus({ analysis, format, formatPercent, onSelect }) {
  const { statuses, days, workDays, load, events } = analysis;
  const knownColors = useRef(new Map());
  const byName = new Map(statuses.map((status) => [status.name, status]));
  const names = [...new Set([...orderedStatuses, ...byName.keys(), ...knownColors.current.keys()])];
  useLayoutEffect(() => {
    for (const { name, color } of statuses) knownColors.current.set(name, color);
  }, [statuses]);
  let offset = 0;

  return (
    <>
      <div className="status-head">
        <strong>
          <AnimatedMetric className="fleet-figure" value={workDays} format={format} integer />
          <small> рабочих авто-дней</small>
        </strong>
        <Badge tone="success">
          <AnimatedMetric className="fleet-figure" value={load} format={formatPercent} />
        </Badge>
      </div>
      <div className="fleet-status-track">
        <div className="fleet-status-rail" style={fleetMotionStyle}>
          {names.map((name) => {
            const status = byName.get(name);
            const share = status && days.length ? status.value / days.length : 0;
            const left = `${offset * 100}%`;
            offset += share;
            return (
              <button
                type="button"
                className="fleet-status-segment"
                key={name}
                style={{
                  transform: `translateX(${left}) scaleX(${share})`,
                  background: status?.color || knownColors.current.get(name) || STATUS_COLORS[name],
                }}
                disabled={!status}
                aria-hidden={!status || undefined}
                aria-label={status ? name : undefined}
                title={status ? `${name}: ${status.value}` : undefined}
                onClick={() => onSelect(name, status.dates)}
              />
            );
          })}
        </div>
      </div>
      <div className="status-list">
        {statuses.map((status) => (
          <button type="button" key={status.name} onClick={() => onSelect(status.name, status.dates)}>
            <i style={{ background: status.color }} />
            <span>{status.name}</span>
            <b>
              <AnimatedMetric className="fleet-figure" value={status.value} format={format} integer /> дн.
            </b>
            <small>
              <AnimatedMetric
                className="fleet-figure"
                value={percent(status.value, days.length)}
                format={formatPercent}
              />
            </small>
            <ChevronRight size={14} />
          </button>
        ))}
      </div>
      <div className="section-foot">
        Дополнительных событий:
        <b><AnimatedMetric className="fleet-figure" value={events} format={format} integer /></b>
        · учитываются отдельно
      </div>
    </>
  );
}
