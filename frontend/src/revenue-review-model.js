import { isTrip, num } from "./model.js";

export function summarizeRevenueReview(rows) {
  const aboveRevenue = [];
  const incomplete = [];
  let comparable = 0;
  let difference = 0;

  for (const row of rows) {
    if (!isTrip(row)) continue;
    const revenue = num(row.revenue);
    const payout = num(row.payout);
    if (revenue === null || payout === null) {
      incomplete.push(row);
      continue;
    }
    comparable += 1;
    if (payout > revenue) {
      aboveRevenue.push(row);
      difference += payout - revenue;
    }
  }

  return { aboveRevenue, incomplete, comparable, difference };
}
