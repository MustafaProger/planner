import React, { useMemo } from "react";
import { ChevronRight } from "lucide-react";
import { AnimatedMetric } from "./animated-metric.jsx";
import { percent } from "./model.js";
import { summarizeRevenueReview } from "./revenue-review-model.js";
import "./revenue-review.css";

const number = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const formatNumber = (value) => (value == null ? "—" : number.format(value));
const formatMoney = (value) => `${formatNumber(value)} ₽`;
const formatShare = (value) => `${formatNumber(value)}%`;

export function RevenueReview({ rows, Section, onSelect }) {
  const { aboveRevenue, incomplete, comparable, difference } = useMemo(
    () => summarizeRevenueReview(rows),
    [rows],
  );
  const total = comparable + incomplete.length;
  const share = percent(aboveRevenue.length, comparable);

  return (
    <Section
      title="Проверка начислений по рейсам"
      subtitle="Заявки по дате начала · доплаты и удержания учитываются отдельно"
    >
      {total > 0 ? (
        <>
          <div className="revenue-review">
            <button
              type="button"
              disabled={!aboveRevenue.length}
              onClick={() => onSelect("Выплата выше выручки", aboveRevenue)}
            >
              <span>Выплата выше выручки</span>
              <strong>
                <AnimatedMetric
                  value={comparable ? aboveRevenue.length : null}
                  format={formatNumber}
                  integer
                />
              </strong>
              <small>
                {share === null ? (
                  "Для сравнения нужны обе суммы"
                ) : (
                  <>
                    <AnimatedMetric value={difference} format={formatMoney} />
                    {" превышения · "}
                    <AnimatedMetric value={share} format={formatShare} />
                    {" сопоставимых рейсов"}
                  </>
                )}
              </small>
              {!!aboveRevenue.length && <ChevronRight size={16} aria-hidden="true" />}
            </button>
            <button
              type="button"
              disabled={!incomplete.length}
              onClick={() => onSelect("Рейсы без полной суммы", incomplete)}
            >
              <span>Не указана сумма</span>
              <strong>
                <AnimatedMetric value={incomplete.length} format={formatNumber} integer />
              </strong>
              <small>Нет выручки, выплаты или обеих сумм</small>
              {!!incomplete.length && <ChevronRight size={16} aria-hidden="true" />}
            </button>
          </div>
          <div className="section-foot">
            <span>
              Рейсы с обеими суммами —{" "}
              <AnimatedMetric value={comparable} format={formatNumber} integer />
              {" из "}
              <AnimatedMetric value={total} format={formatNumber} integer />
              . Суммы относятся к отдельным строкам.
            </span>
          </div>
        </>
      ) : (
        <p className="muted">За выбранный период рейсов нет.</p>
      )}
    </Section>
  );
}
