import React, { useLayoutEffect, useRef } from "react";
import { REPORT_MOTION_MS, easeOutProgress } from "./report-motion.js";
import "./animated-metric.css";

const activeMetrics = new Map();
let animationFrame;
let metricObserver;
let motionPreference;

function reducedMotion() {
  motionPreference ??= window.matchMedia("(prefers-reduced-motion: reduce)");
  return motionPreference.matches;
}

function stopMetric(node) {
  if (activeMetrics.delete(node)) metricObserver?.unobserve(node);
}

function advanceMetrics(now) {
  animationFrame = undefined;
  const reduced = reducedMotion();
  for (const [node, { from, value, start, write }] of activeMetrics) {
    const elapsed = Math.max(0, now - start);
    if (reduced || elapsed >= REPORT_MOTION_MS) {
      write(value);
      stopMetric(node);
    } else {
      const progress = easeOutProgress(elapsed / REPORT_MOTION_MS);
      write(from * (1 - progress) + value * progress);
    }
  }
  if (activeMetrics.size) animationFrame = requestAnimationFrame(advanceMetrics);
}

function animateMetric(node, from, value, write) {
  const observed = activeMetrics.has(node);
  activeMetrics.set(node, { from, value, start: performance.now(), write });

  if (typeof IntersectionObserver === "function" && !observed) {
    metricObserver ??= new IntersectionObserver((entries) => {
      for (const { target, isIntersecting } of entries) {
        const metric = activeMetrics.get(target);
        if (metric && !isIntersecting) {
          metric.write(metric.value);
          stopMetric(target);
        }
      }
    });
    metricObserver.observe(node);
  }

  animationFrame ??= requestAnimationFrame(advanceMetrics);
}

const firstValue = Symbol("first value");

export function AnimatedMetric({ value, format, integer = false, className = "" }) {
  const visible = useRef(null);
  const displayed = useRef(0);
  const previous = useRef(firstValue);
  const formatter = useRef();
  const target = format(value);

  useLayoutEffect(() => {
    const node = visible.current;
    return () => stopMetric(node);
  }, []);

  useLayoutEffect(() => {
    const node = visible.current;
    formatter.current = { format, integer };
    const write = (next) => {
      displayed.current = next;
      const options = formatter.current;
      const rounded = options.integer && Number.isFinite(next) ? Math.round(next) : next;
      const text = options.format(Object.is(rounded, -0) ? 0 : rounded);
      if (node.textContent !== text) node.textContent = text;
    };

    if (Object.is(previous.current, value)) {
      write(displayed.current);
      return;
    }
    previous.current = value;
    const from = Number.isFinite(displayed.current) ? displayed.current : 0;
    if (reducedMotion() || !Number.isFinite(value) || from === value) {
      stopMetric(node);
      write(value);
      return;
    }
    write(from);
    animateMetric(node, from, value, write);
  });

  return (
    <span className={`animated-metric ${className}`} data-target={target}>
      <span className="animated-metric__target">{target}</span>
      <span className="animated-metric__visible" aria-hidden="true" ref={visible} />
    </span>
  );
}
