import React, { useId, useLayoutEffect, useRef } from "react";
import {
  AreaChart,
  Area,
  AreaRevealShape,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  usePlotArea,
} from "recharts";
import { REPORT_EASE_OUT, REPORT_MOTION_MS, easeOutProgress } from "./report-motion.js";
import "./report-data-motion.css";

function animateSeries(node, keyframes) {
  return node?.animate?.(keyframes, {
    duration: REPORT_MOTION_MS,
    easing: REPORT_EASE_OUT,
    fill: "backwards",
  });
}

function SeriesMask({ id, data }) {
  const plot = usePlotArea();
  const mask = useRef(null);
  const width = plot?.width;
  useLayoutEffect(() => {
    if (!width) return;
    const animation = animateSeries(mask.current, [
      { transform: "scaleX(.025)" },
      { transform: "scaleX(1)" },
    ]);
    return () => animation?.cancel();
  }, [data, width]);
  if (!plot) return null;
  return (
    <defs>
      <clipPath id={id}>
        <rect
          ref={mask}
          className="money-series-mask"
          x={plot.x - 2}
          y={plot.y - 2}
          width={plot.width + 4}
          height={plot.height + 4}
        />
      </clipPath>
    </defs>
  );
}

function SweptArea({ maskId, series, ...props }) {
  const shapeId = useId();
  const preview = useRef(null);
  useLayoutEffect(() => {
    const animation = animateSeries(preview.current, [
      { opacity: 0.26 },
      { offset: 0.8, opacity: 0.2 },
      { opacity: 0 },
    ]);
    return () => animation?.cancel();
  }, [series]);
  return (
    <>
      <defs><g id={shapeId}><AreaRevealShape {...props} /></g></defs>
      <use ref={preview} href={`#${shapeId}`} className="money-series-preview" />
      <use href={`#${shapeId}`} clipPath={`url(#${maskId})`} />
    </>
  );
}

export default function MoneyChart({ data, bar, onSelect, reduced, date, short, money }) {
  const C = bar ? BarChart : AreaChart;
  const id = useId();
  const maskId = `money-sweep-${id}`;
  const fillId = `revenue-fill-${id}`;
  const sweep = !bar && data.length > 1 && !reduced;
  const shape = sweep ? <SweptArea maskId={maskId} series={data} /> : undefined;
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <C
          data={data}
          margin={{ top: 12, right: 8, left: 0, bottom: 0 }}
          onClick={(e) => {
            const row =
              e?.activePayload?.[0]?.payload ??
              data[Number(e?.activeTooltipIndex)];
            if (row) onSelect?.(row);
          }}
          accessibilityLayer
        >
          <defs>
            <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4377c3" stopOpacity={0.18} />
              <stop offset="100%" stopColor="#4377c3" stopOpacity={0.015} />
            </linearGradient>
          </defs>
          {sweep && <SeriesMask id={maskId} data={data} />}
          <CartesianGrid
            vertical={false}
            stroke="#e9edf1"
            strokeDasharray="3 4"
          />
          <XAxis
            dataKey="name"
            tickLine={false}
            axisLine={false}
            tick={{ fill: "#77818e", fontSize: 11 }}
            tickFormatter={(v) =>
              /^\d{4}-/.test(v)
                ? v.length === 7
                  ? new Date(v + "-15").toLocaleDateString("ru-RU", {
                      month: "short",
                    })
                  : date(v)
                : v
            }
            minTickGap={28}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={65}
            tick={{ fill: "#77818e", fontSize: 11 }}
            tickFormatter={short}
          />
          <Tooltip
            formatter={(v, name) => [money(v), name]}
            contentStyle={{
              borderRadius: 10,
              border: "1px solid #e6e9ef",
              fontSize: 13,
            }}
            labelFormatter={(v) => v}
          />
          {bar ? (
            <>
              <Bar
                dataKey="revenue"
                name="Выручка"
                fill="#477dc6"
                radius={[4, 4, 0, 0]}
                maxBarSize={42}
                isAnimationActive={!reduced}
                animationDuration={REPORT_MOTION_MS}
                animationEasing={easeOutProgress}
              />
              <Bar
                dataKey="payout"
                name="Выплаты"
                fill="#89b9a7"
                radius={[4, 4, 0, 0]}
                maxBarSize={42}
                isAnimationActive={!reduced}
                animationDuration={REPORT_MOTION_MS}
                animationEasing={easeOutProgress}
              />
            </>
          ) : (
            <>
              <Area
                type="monotone"
                dataKey="revenue"
                name="Выручка"
                stroke="#4178c7"
                strokeWidth={2.5}
                fill={`url(#${fillId})`}
                connectNulls={false}
                isAnimationActive={false}
                shape={shape}
              />
              <Area
                type="monotone"
                dataKey="payout"
                name="Выплаты"
                stroke="#83af9f"
                strokeWidth={2}
                fill="transparent"
                connectNulls={false}
                isAnimationActive={false}
                shape={shape}
              />
            </>
          )}
        </C>
      </ResponsiveContainer>
    </div>
  );
}
