export const REPORT_MOTION_MS = 800;

// CSS equivalent of easeOutProgress for the graph and fleet status bar.
export const REPORT_EASE_OUT = "cubic-bezier(0.333333, 0.666667, 0.666667, 1)";

export function easeOutProgress(progress) {
  return 1 - (1 - progress) ** 2;
}
