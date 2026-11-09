import assert from "node:assert/strict";
import test from "node:test";
import { summarizeRevenueReview } from "./revenue-review-model.js";

test("revenue review compares known trip amounts and retains original rows for drilldown", () => {
  const above = { id: "above", revenue: 0, payout: 125 };
  const incomplete = { id: "missing", revenue: null, payout: 50 };
  const result = summarizeRevenueReview([
    { id: "equal", revenue: 0, payout: 0 },
    { id: "covered", revenue: 500, payout: 100 },
    above,
    incomplete,
    { id: "cancelled", cancelled: true, revenue: 0, payout: 50 },
    { id: "additional", type: "Доплата", revenue: 0, payout: 100 },
  ]);

  assert.equal(result.comparable, 3);
  assert.equal(result.difference, 125);
  assert.equal(result.aboveRevenue.length, 1);
  assert.equal(result.aboveRevenue[0], above);
  assert.equal(result.incomplete.length, 1);
  assert.equal(result.incomplete[0], incomplete);
});

test("revenue review reports absent amounts without treating them as zero", () => {
  const row = { id: "invalid", revenue: "100", payout: undefined };
  const result = summarizeRevenueReview([row]);
  assert.deepEqual(result, {
    aboveRevenue: [],
    incomplete: [row],
    comparable: 0,
    difference: 0,
  });
});
