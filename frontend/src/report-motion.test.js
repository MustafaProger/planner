import { test } from "node:test";
import assert from "node:assert/strict";
import { createMetricMotion, metricMotionFrame } from "./report-motion.js";

test("large changes fade the previous number and count only near the new total", () => {
  const old = 16_000_000;
  const target = 144;
  const motion = createMetricMotion(old, target, false, 1);
  assert.deepEqual(metricMotionFrame(motion, 0), { next: old, opacity: 1 });
  const fade = metricMotionFrame(motion, 80);
  assert.equal(fade.next, old);
  assert.ok(fade.opacity > 0 && fade.opacity < 1);

  const newValue = metricMotionFrame(motion, 120);
  assert.ok(newValue.next > target && newValue.next < target + 3);
  assert.ok(newValue.opacity < fade.opacity);
  const late = metricMotionFrame(motion, 800);
  assert.ok(late.next > target && late.next < newValue.next);
  assert.equal(late.opacity, 1);
  assert.deepEqual(metricMotionFrame(motion, 1150), { next: target, opacity: 1, done: true });
});

test("nearby changes count from the displayed value without fading or reversing", () => {
  const motion = createMetricMotion(40, 24, true, 1);
  const frames = Array.from({ length: 24 }, (_, i) => metricMotionFrame(motion, i * 50));
  assert.equal(frames[0].next, 40);
  assert.equal(frames.at(-1).next, 24);
  assert.ok(frames.every(({ opacity }) => opacity === 1));
  assert.ok(frames.every(({ next }, i) => i === 0 || next <= frames[i - 1].next));
  assert.ok(frames[8].next > 32);
});

test("large increases and sign changes stay on their final side of zero", () => {
  const increase = createMetricMotion(144, 70_000_000, false, 1);
  assert.equal(metricMotionFrame(increase, 120).next, 68_950_000);
  const crossZero = createMetricMotion(-16_000_000, 0.4, false, 1);
  assert.equal(metricMotionFrame(crossZero, 120).next, 0);
  assert.ok(metricMotionFrame(crossZero, 700).next > 0);
  assert.equal(metricMotionFrame(crossZero, 1150).next, 0.4);
  const zero = createMetricMotion(-16_000_000, 0, false, 1);
  assert.equal(metricMotionFrame(zero, 120).next, -0.8);
  assert.equal(metricMotionFrame(zero, 1150).next, 0);
});

test("retargeting starts from the number and opacity currently displayed", () => {
  const first = createMetricMotion(16_000_000, 144, false, 1);
  const current = metricMotionFrame(first, 210);
  const latest = createMetricMotion(current.next, 17_000_000, false, current.opacity);
  assert.deepEqual(metricMotionFrame(latest, 0), current);
  assert.equal(metricMotionFrame(latest, 1150).next, 17_000_000);
});
