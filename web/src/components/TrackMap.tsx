"use client";

import { useId } from "react";
import { motion } from "motion/react";
import type { CornerPoint, TrackPoint } from "@/lib/types";

/**
 * Renders a real GPS-traced track outline as an animated SVG path — the line
 * "draws itself" in on mount via Motion's pathLength animation.
 *
 * Points come from one real fastest-lap telemetry trace. We fit them to a square
 * viewBox, preserving aspect ratio (no stretching), and flip Y since SVG's y-axis
 * grows downward while the raw telemetry's grows upward.
 *
 * Styled like a broadcast-graphics track map rather than a neon line: a wide
 * dark "tarmac" stroke with a crisp drop shadow for depth, and a slim violet
 * racing-line stroke on top — violet nods to F1's own broadcast convention for
 * a session's fastest sector, fitting for a qualifying comparison tool. No
 * blur/glow.
 *
 * Corner numbers (optional) are nudged outward, away from the track's own
 * centroid, so a small label pill sits just off the line instead of on it.
 */
export default function TrackMap({ points, corners }: { points: TrackPoint[]; corners?: CornerPoint[] }) {
  const uid = useId();
  if (!points || points.length === 0) return null;

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const centroidX = (minX + maxX) / 2;
  const centroidY = (minY + maxY) / 2;

  const size = 100;
  const pad = corners && corners.length > 0 ? 16 : 10; // extra room for label pills
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const scale = (size - pad * 2) / Math.max(spanX, spanY);

  const project = (x: number, y: number) => {
    const sx = (x - minX) * scale + pad + (size - pad * 2 - spanX * scale) / 2;
    const syRaw = (y - minY) * scale + pad + (size - pad * 2 - spanY * scale) / 2;
    return [sx, size - syRaw] as const; // flip Y
  };
  const toSvg = (p: TrackPoint) => project(p.x, p.y).map((n) => n.toFixed(2)).join(",");

  const d = "M " + points.map(toSvg).join(" L ");
  const start = toSvg(points[0]).split(",").map(Number);
  const shadowId = `trackmap-shadow-${uid}`;

  const labels = (corners ?? []).map((c) => {
    const [px, py] = project(c.x, c.y);
    const [cx, cy] = project(centroidX, centroidY);
    const dx = px - cx, dy = py - cy;
    const mag = Math.hypot(dx, dy) || 1;
    const lx = px + (dx / mag) * 4.4;
    const ly = py + (dy / mag) * 4.4;
    return { key: `${c.number}${c.letter ?? ""}`, x: lx, y: ly, text: `${c.number}${c.letter ?? ""}` };
  });

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full h-full">
      <defs>
        <filter id={shadowId} x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="0.9" stdDeviation="0.7" floodColor="#000000" floodOpacity="0.45" />
        </filter>
      </defs>

      {/* tarmac */}
      <motion.path
        d={d}
        fill="none"
        stroke="#3F4654"
        strokeWidth={3.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${shadowId})`}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ pathLength: { duration: 0.9, ease: [0.16, 1, 0.3, 1] }, opacity: { duration: 0.2 } }}
      />

      {/* racing line */}
      <motion.path
        d={d}
        fill="none"
        stroke="#A855F7"
        strokeWidth={1.1}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ pathLength: { duration: 0.9, ease: [0.16, 1, 0.3, 1], delay: 0.08 }, opacity: { duration: 0.2, delay: 0.08 } }}
      />

      <motion.circle
        cx={start[0]}
        cy={start[1]}
        r={1.9}
        fill="#A855F7"
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.75, duration: 0.3, type: "spring", stiffness: 400 }}
      />

      {labels.map((l, i) => (
        <motion.g
          key={l.key}
          initial={{ opacity: 0, scale: 0.4 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.85 + i * 0.012, duration: 0.25, type: "spring", stiffness: 420 }}
        >
          <circle cx={l.x} cy={l.y} r={1.9} fill="#15131C" stroke="#A855F7" strokeWidth={0.35} />
          <text
            x={l.x}
            y={l.y}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={2.1}
            fontWeight={600}
            fill="#F4F0FA"
            style={{ fontFamily: "ui-sans-serif, system-ui, sans-serif" }}
          >
            {l.text}
          </text>
        </motion.g>
      ))}
    </svg>
  );
}
