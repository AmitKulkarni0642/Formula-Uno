"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, type Variants } from "motion/react";
import { ApiError, getCircuitProfile, getHealth, getQualifyingPrediction, getRacePrediction } from "@/lib/api";
import type { Circuit, CircuitProfile, QualifyingPrediction, RacePrediction } from "@/lib/types";
import CircuitProfileCard from "@/components/CircuitProfileCard";
import { formatLapTime } from "@/lib/format";

type Session = "race" | "qualifying";

const EASE = [0.16, 1, 0.3, 1] as const; // expo-out — the "quality" easing curve

export default function Home() {
  const [circuits, setCircuits] = useState<Circuit[]>([]);
  const [years, setYears] = useState<number[]>([]);
  const [circuit, setCircuit] = useState<string>("");
  const [year, setYear] = useState<number>(2025);
  const [session, setSession] = useState<Session>("race");

  const [raceData, setRaceData] = useState<RacePrediction | null>(null);
  const [qualData, setQualData] = useState<QualifyingPrediction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [profile, setProfile] = useState<CircuitProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  useEffect(() => {
    getHealth()
      .then((h) => {
        const sorted = [...h.circuits].sort((a, b) => a.label.localeCompare(b.label));
        setCircuits(sorted);
        setCircuit(sorted[0]?.key ?? "");
        setYears([...h.years].sort((a, b) => b - a));
        setYear(Math.max(...h.years));
      })
      .catch((e) =>
        setError(
          e instanceof ApiError
            ? e.message
            : "Couldn't reach the Formula Uno API — is it running? (python run.py api)"
        )
      );
  }, []);

  // Circuit facts (history, track map, records) depend only on the circuit, not
  // year/session — fetch once per circuit change, not on every selector change.
  useEffect(() => {
    if (!circuit) return;
    setProfileLoading(true);
    getCircuitProfile(circuit)
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setProfileLoading(false));
  }, [circuit]);

  useEffect(() => {
    if (!circuit) return;
    setLoading(true);
    setError(null);
    const fetcher = session === "race" ? getRacePrediction(circuit, year) : getQualifyingPrediction(circuit, year);
    fetcher
      .then((data) => {
        if (session === "race") setRaceData(data as RacePrediction);
        else setQualData(data as QualifyingPrediction);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Prediction failed."))
      .finally(() => setLoading(false));
  }, [circuit, year, session]);

  const circuitLabel = circuits.find((c) => c.key === circuit)?.label ?? circuit;
  const viewKey = `${session}-${circuit}-${year}`;

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-4 py-8 sm:px-6">
      <motion.header
        className="mb-8"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <div className="flex items-start justify-between flex-wrap gap-2">
          <div>
            <p className="text-xs tracking-widest uppercase text-red-600 font-semibold mb-1">
              Formula Uno
            </p>
            <h1 className="text-3xl font-bold tracking-tight">
              <AnimatePresence mode="wait">
                <motion.span
                  key={circuitLabel + year}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.25, ease: EASE }}
                  className="inline-block"
                >
                  {circuitLabel || "Loading…"} {year ? `— ${year}` : ""}
                </motion.span>
              </AnimatePresence>
            </h1>
          </div>
          <Link
            href="/compare"
            className="text-sm text-black/50 dark:text-white/50 hover:text-black dark:hover:text-white transition-colors mt-1"
          >
            Compare drivers →
          </Link>
        </div>
      </motion.header>

      <motion.div
        className="flex flex-wrap items-end gap-4 mb-8 pb-6 border-b border-black/10 dark:border-white/10"
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.08, ease: EASE }}
      >
        <Field label="Circuit">
          <select
            className="rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm transition-colors hover:border-black/30 dark:hover:border-white/30 focus:outline-none focus:ring-2 focus:ring-red-600/40"
            value={circuit}
            onChange={(e) => setCircuit(e.target.value)}
          >
            {circuits.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Season">
          <select
            className="rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm transition-colors hover:border-black/30 dark:hover:border-white/30 focus:outline-none focus:ring-2 focus:ring-red-600/40"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </Field>
        <SegmentedControl session={session} onChange={setSession} />
      </motion.div>

      <CircuitProfileCard profile={profile} loading={profileLoading} />

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0, marginBottom: 0 }}
            animate={{ opacity: 1, height: "auto", marginBottom: 24 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 text-sm">
              {error}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex items-center gap-2 text-sm text-black/50 dark:text-white/50"
          >
            <motion.span
              className="inline-block h-3.5 w-3.5 rounded-full border-2 border-red-600/30 border-t-red-600"
              animate={{ rotate: 360 }}
              transition={{ duration: 0.7, repeat: Infinity, ease: "linear" }}
            />
            Simulating…
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        {!loading && session === "race" && raceData && (
          <motion.div
            key={viewKey}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.35, ease: EASE }}
          >
            <RaceView data={raceData} />
          </motion.div>
        )}
        {!loading && session === "qualifying" && qualData && (
          <motion.div
            key={viewKey}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.35, ease: EASE }}
          >
            <QualView data={qualData} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SegmentedControl({ session, onChange }: { session: Session; onChange: (s: Session) => void }) {
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs uppercase tracking-wide text-black/50 dark:text-white/50">{label}</span>
      {children}
    </label>
  );
}

const gridVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.05 } },
};
const cardVariants: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: EASE } },
};

function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
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

function errorBg(n: number, max: number) {
  if (n === 0) return "";
  const intensity = Math.min(n / max, 1);
  return `rgba(225, 6, 0, ${0.08 + intensity * 0.3})`;
}

const rowVariants: Variants = {
  hidden: { opacity: 0, x: -8 },
  show: { opacity: 1, x: 0, transition: { duration: 0.25, ease: EASE } },
};

function RaceView({ data }: { data: RacePrediction }) {
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

function QualView({ data }: { data: QualifyingPrediction }) {
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
