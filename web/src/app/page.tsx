"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ApiError, getCircuitProfile, getHealth, getQualifyingPrediction, getRacePrediction } from "@/lib/api";
import type { Circuit, CircuitProfile, QualifyingPrediction, RacePrediction } from "@/lib/types";
import CircuitProfileCard from "@/components/CircuitProfileCard";
import { RaceView, QualView, SegmentedControl, type Session } from "@/components/PredictionViews";

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
        <div>
          <p className="text-xs tracking-widest uppercase text-black/40 dark:text-white/40 font-semibold mb-1">
            Reconstruction, not forecast — see an event's Preview tab for the live version
          </p>
          <h1 className="text-3xl font-display font-bold tracking-tight">
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
      </motion.header>

      <motion.div
        className="flex flex-wrap items-end gap-4 mb-8 pb-6 border-b border-black/10 dark:border-white/10"
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.08, ease: EASE }}
      >
        <Field label="Circuit">
          <select
            className="rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm transition-colors hover:border-black/30 dark:hover:border-white/30 focus:outline-none focus:ring-2 focus:ring-accent/40"
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
            className="rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm transition-colors hover:border-black/30 dark:hover:border-white/30 focus:outline-none focus:ring-2 focus:ring-accent/40"
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
              className="inline-block h-3.5 w-3.5 rounded-full border-2 border-accent/30 border-t-accent"
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs uppercase tracking-wide text-black/50 dark:text-white/50">{label}</span>
      {children}
    </label>
  );
}

