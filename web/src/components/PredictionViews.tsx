"use client";

import { AnimatePresence, motion, type Variants } from "motion/react";
import type { QualifyingPrediction, RacePrediction } from "@/lib/types";
import { formatLapTime } from "@/lib/format";

export type Session = "race" | "qualifying";

const EASE = [0.16, 1, 0.3, 1] as const;

const gridVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.05 } },
};
const cardVariants: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: EASE } },
};
const rowVariants: Variants = {
  hidden: { opacity: 0, x: -8 },
  show: { opacity: 1, x: 0, transition: { duration: 0.25, ease: EASE } },
};

export function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <motion.div
      variants={cardVariants}
      whileHover={{ y: -2 }}
      className="rounded-xl border border-black/10 dark:border-white/10 px-4 py-3 overflow-hidden transition-shadow hover:shadow-md"
    >
      <p className="text-xs uppercase tracking-wide text-black/50 dark:text-white/50 mb-1">{label}</p>
      <AnimatePresence mode="wait">
        <motion.p
          key={value}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25, ease: EASE }}
          className="text-2xl font-semibold tabular-nums"
        >
          {value}
        </motion.p>
      </AnimatePresence>
      {hint && <p className="text-xs text-black/40 dark:text-white/40 mt-0.5">{hint}</p>}
    </motion.div>
  );
}

export function SegmentedControl({ session, onChange }: { session: Session; onChange: (s: Session) => void }) {
  return (
    <div className="flex gap-1 bg-black/5 dark:bg-white/10 rounded-lg p-1">
      {(["race", "qualifying"] as const).map((s) => (
        <motion.button
          key={s}
          onClick={() => onChange(s)}
          whileTap={{ scale: 0.96 }}
          className={`relative px-3 py-1.5 rounded-md text-sm font-medium capitalize transition-colors ${
            session === s
              ? "text-black dark:text-white"
              : "text-black/60 dark:text-white/60 hover:text-black dark:hover:text-white"
          }`}
        >
          {session === s && (
            <motion.div
              layoutId="segment-pill"
              className="absolute inset-0 bg-white dark:bg-neutral-800 rounded-md shadow-sm"
              transition={{ type: "spring", stiffness: 500, damping: 35 }}
            />
          )}
          <span className="relative z-10">{s}</span>
        </motion.button>
      ))}
    </div>
  );
}

function errorBg(n: number, max: number) {
  if (n === 0) return "";
  const intensity = Math.min(n / max, 1);
  return `rgba(225, 6, 0, ${0.08 + intensity * 0.3})`;
}

/**
 * Shared between the standalone /predictions dashboard and an event page's
 * Preview tab — same reconstruction data, same table, same component. One
 * place to fix if the prediction schema ever changes.
 */
export function RaceView({ data }: { data: RacePrediction }) {
  const m = data.metrics;
  return (
    <div>
      <motion.div
        className="flex items-center gap-3 mb-6 text-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1, duration: 0.3 }}
      >
        <span
          className={`px-2 py-0.5 rounded-full text-xs font-medium ${
            data.in_sample
              ? "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
              : "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300"
          }`}
        >
          {data.in_sample ? "In-sample" : "Out-of-sample"}
        </span>
        <span className="text-black/50 dark:text-white/50">
          Model: <code className="font-mono">{data.model}</code> · {data.approach}
        </span>
      </motion.div>

      <motion.div
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8"
        variants={gridVariants}
        initial="hidden"
        animate="show"
      >
        <MetricCard label="Mean position error" value={`${m.mean_position_error.toFixed(2)} places`} />
        <MetricCard
          label="Fleet lap-time RMSE"
          value={m.fleet_lap_rmse_s !== null ? `${m.fleet_lap_rmse_s.toFixed(3)}s` : "—"}
        />
        <MetricCard label="Within 2 positions" value={`${m.within_2_positions}/${m.drivers_compared}`} />
        <MetricCard label="Exact positions" value={`${m.exact_positions}/${m.drivers_compared}`} />
      </motion.div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-black/50 dark:text-white/50 border-b border-black/10 dark:border-white/10">
            <th className="py-2 pr-3">Predicted</th>
            <th className="py-2 pr-3">Driver</th>
            <th className="py-2 pr-3">Team</th>
            <th className="py-2 pr-3">Actual</th>
            <th className="py-2 pr-3">Error</th>
            <th className="py-2 pr-3">Lap RMSE</th>
          </tr>
        </thead>
        <motion.tbody variants={gridVariants} initial="hidden" animate="show">
          {data.results.map((r) => (
            <motion.tr
              key={r.driver}
              variants={rowVariants}
              whileHover={{ backgroundColor: "rgba(128,128,128,0.06)" }}
              className="border-b border-black/5 dark:border-white/5"
            >
              <td className="py-1.5 pr-3 tabular-nums">P{r.sim_position}</td>
              <td className="py-1.5 pr-3 font-medium">{r.driver}</td>
              <td className="py-1.5 pr-3 text-black/60 dark:text-white/60">{r.team}</td>
              <td className="py-1.5 pr-3 tabular-nums">P{r.actual_position}</td>
              <td
                className="py-1.5 pr-3 tabular-nums rounded transition-colors"
                style={{ backgroundColor: errorBg(r.position_error, 10) }}
              >
                {r.position_error}
              </td>
              <td className="py-1.5 pr-3 tabular-nums text-black/60 dark:text-white/60">
                {r.lap_rmse_s !== null ? `${r.lap_rmse_s.toFixed(3)}s` : "—"}
              </td>
            </motion.tr>
          ))}
        </motion.tbody>
      </table>
    </div>
  );
}

export function QualView({ data }: { data: QualifyingPrediction }) {
  const m = data.metrics;
  return (
    <div>
      <motion.div
        className="mb-6 text-sm text-black/50 dark:text-white/50"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1, duration: 0.3 }}
      >
        Model: <code className="font-mono">{data.model}</code> · {data.approach}
      </motion.div>

      <motion.div
        className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8"
        variants={gridVariants}
        initial="hidden"
        animate="show"
      >
        <MetricCard label="Mean grid error" value={`${m.mean_grid_error.toFixed(2)} places`} />
        <MetricCard label="Lap-time RMSE" value={`${m.lap_time_rmse_s.toFixed(3)}s`} />
        <MetricCard label="Within 2 positions" value={`${m.within_2_positions}/${m.drivers}`} />
        <MetricCard label="Exact positions" value={`${m.exact_positions}/${m.drivers}`} />
      </motion.div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-black/50 dark:text-white/50 border-b border-black/10 dark:border-white/10">
            <th className="py-2 pr-3">Predicted</th>
            <th className="py-2 pr-3">Driver</th>
            <th className="py-2 pr-3">Team</th>
            <th className="py-2 pr-3">Predicted (s)</th>
            <th className="py-2 pr-3">Actual (s)</th>
            <th className="py-2 pr-3">Actual</th>
            <th className="py-2 pr-3">Error</th>
          </tr>
        </thead>
        <motion.tbody variants={gridVariants} initial="hidden" animate="show">
          {data.results.map((r) => (
            <motion.tr
              key={r.driver}
              variants={rowVariants}
              whileHover={{ backgroundColor: "rgba(128,128,128,0.06)" }}
              className="border-b border-black/5 dark:border-white/5"
            >
              <td className="py-1.5 pr-3 tabular-nums">P{r.pred_grid}</td>
              <td className="py-1.5 pr-3 font-medium">{r.driver}</td>
              <td className="py-1.5 pr-3 text-black/60 dark:text-white/60">{r.team}</td>
              <td className="py-1.5 pr-3 tabular-nums">{formatLapTime(r.predicted_time_s)}</td>
              <td className="py-1.5 pr-3 tabular-nums">{formatLapTime(r.actual_time_s)}</td>
              <td className="py-1.5 pr-3 tabular-nums">P{r.actual_grid}</td>
              <td
                className="py-1.5 pr-3 tabular-nums rounded transition-colors"
                style={{ backgroundColor: errorBg(r.grid_error, 10) }}
              >
                {r.grid_error}
              </td>
            </motion.tr>
          ))}
        </motion.tbody>
      </table>
    </div>
  );
}
