import React, { useLayoutEffect, useRef } from "react";
import { createMetricMotion, metricMotionFrame } from "./report-motion.js";
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
  for (const [node, metric] of activeMetrics) {
    if (reduced) {
      metric.write(metric.value);
      stopMetric(node);
      continue;
    }
    const frame = metricMotionFrame(metric, Math.max(0, now - metric.start));
    metric.write(frame.next, frame.opacity);
    if (frame.done) stopMetric(node);
  }
  if (activeMetrics.size) animationFrame = requestAnimationFrame(advanceMetrics);
}

function animateMetric(node, motion, write) {
  const observed = activeMetrics.has(node);
  activeMetrics.set(node, { ...motion, start: performance.now(), write });

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

function formatMetric(value, format, integer) {
  const rounded = integer && Number.isFinite(value) ? Math.round(value) : value;
  return format(Object.is(rounded, -0) ? 0 : rounded);
}

export function AnimatedMetric({ value, format, integer = false, className = "" }) {
  const visible = useRef(null);
  const displayed = useRef({ value: undefined, opacity: 1 });
  const previous = useRef(firstValue);
  const formatter = useRef();
  const target = formatMetric(value, format, integer);

  useLayoutEffect(() => {
    const node = visible.current;
    return () => stopMetric(node);
  }, []);

  useLayoutEffect(() => {
    const node = visible.current;
    formatter.current = { format, integer };
    const current = displayed.current;
    const write = (next, opacity = 1, force = false) => {
      if (current.opacity !== opacity) {
        node.style.opacity = opacity === 1 ? "" : String(opacity);
        current.opacity = opacity;
      }
      if (!force && Object.is(current.value, next)) return;
      current.value = next;
      const text = formatMetric(next, formatter.current.format, formatter.current.integer);
      if (node.textContent !== text) node.textContent = text;
    };

    if (Object.is(previous.current, value)) {
      write(current.value, current.opacity, true);
      return;
    }
    previous.current = value;
    const from = current.value;
    if (
      reducedMotion() ||
      !Number.isFinite(value) ||
      !Number.isFinite(from) ||
      formatMetric(from, format, integer) === target
    ) {
      stopMetric(node);
      write(value, 1, true);
      return;
    }
    write(from, current.opacity, true);
    animateMetric(node, createMetricMotion(from, value, integer, current.opacity), write);
  });

  return (
    <span className={`animated-metric ${className}`} data-target={target}>
      <span className="animated-metric__target">{target}</span>
      <span className="animated-metric__visible" aria-hidden="true" ref={visible} />
    </span>
  );
}
