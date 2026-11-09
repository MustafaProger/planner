import React from "react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function MoneyChart({ data, bar, onSelect, reduced, date, short, money }) {
  const C = bar ? BarChart : AreaChart;
  const animate = !reduced && (bar || data.length <= 120);
  return (
    <div className={`chart${!animate && !reduced ? " chart--reveal" : ""}`}>
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
            <linearGradient id="revenue-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4377c3" stopOpacity={0.18} />
              <stop offset="100%" stopColor="#4377c3" stopOpacity={0.015} />
            </linearGradient>
          </defs>
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
                isAnimationActive={animate}
                animationDuration={220}
                animationEasing="ease-out"
              />
              <Bar
                dataKey="payout"
                name="Выплаты"
                fill="#89b9a7"
                radius={[4, 4, 0, 0]}
                maxBarSize={42}
                isAnimationActive={animate}
                animationDuration={220}
                animationEasing="ease-out"
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
                fill="url(#revenue-fill)"
                connectNulls={false}
                isAnimationActive={animate}
                animationDuration={220}
                animationEasing="ease-out"
              />
              <Area
                type="monotone"
                dataKey="payout"
                name="Выплаты"
                stroke="#83af9f"
                strokeWidth={2}
                fill="transparent"
                connectNulls={false}
                isAnimationActive={animate}
                animationDuration={220}
                animationEasing="ease-out"
              />
            </>
          )}
        </C>
      </ResponsiveContainer>
    </div>
  );
}
