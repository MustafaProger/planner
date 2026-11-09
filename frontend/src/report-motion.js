export const REPORT_MOTION_MS = 800;

// CSS equivalent of easeOutProgress for the graph and fleet status bar.
export const REPORT_EASE_OUT = "cubic-bezier(0.333333, 0.666667, 0.666667, 1)";

export function easeOutProgress(progress) {
  return 1 - (1 - progress) ** 2;
}

const METRIC_MOTION_MS = 1150;
const METRIC_HANDOFF_MS = 120;
const METRIC_FADE_IN_MS = 180;
const METRIC_FRAME_MS = 1000 / 30;
const METRIC_FADED_OPACITY = 0.2;

export function createMetricMotion(from, value, integer, opacity) {
  const difference = from - value;
  const precision = integer ? 1 : 0.1;
  const tail = Math.max(precision * 8, Math.abs(value) * 0.015);
  const handoff = Math.abs(difference) > tail * 4 ? METRIC_HANDOFF_MS : 0;
  const tailStart = value + Math.sign(difference) * tail;
  const crossesZero = value !== 0 && Math.sign(tailStart) !== Math.sign(value);
  return {
    from,
    value,
    precision,
    handoff,
    // A jump across zero counts within the sign of the new result.
    countFrom: handoff ? (crossesZero ? 0 : tailStart) : from,
    opacity,
  };
}

export function metricMotionFrame(motion, elapsed) {
  const { from, value, precision, handoff, countFrom, opacity } = motion;
  if (elapsed >= METRIC_MOTION_MS) return { next: value, opacity: 1, done: true };
  if (elapsed < handoff) {
    return { next: from, opacity: opacity + (METRIC_FADED_OPACITY - opacity) * (elapsed / handoff) };
  }

  const countingTime = elapsed - handoff;
  const sampledTime = Math.floor(countingTime / METRIC_FRAME_MS) * METRIC_FRAME_MS;
  const progress = sampledTime / (METRIC_MOTION_MS - handoff);
  const eased = progress ** 2 * (3 - 2 * progress);
  const offset = countFrom - value;
  const remaining = Math.abs(offset) * (1 - eased);
  // Use coarser steps at a distance, so the last digits settle gradually.
  const step = Math.max(precision, 10 ** Math.floor(Math.log10(remaining / 8)));
  const rounded = Math.min(Math.abs(offset), Math.round(remaining / step) * step);
  const fadeStart = handoff ? METRIC_FADED_OPACITY : opacity;
  const fadeProgress = Math.min(1, countingTime / METRIC_FADE_IN_MS);
  return {
    next: sampledTime ? value + Math.sign(offset) * rounded : countFrom,
    opacity: fadeStart + (1 - fadeStart) * fadeProgress,
  };
}
