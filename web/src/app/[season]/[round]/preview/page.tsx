"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import {
  getCircuitProfile, getHealth, getQualifyingPrediction, getRacePrediction, getSchedule,
} from "@/lib/api";
import { findCircuitKey } from "@/lib/circuitLookup";
import type { Circuit, CircuitProfile, QualifyingPrediction, RacePrediction } from "@/lib/types";
import { RaceView, QualView, SegmentedControl, type Session } from "@/components/PredictionViews";
import CircuitProfileCard from "@/components/CircuitProfileCard";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * Folds the standalone /predictions dashboard's circuit-prediction model
 * into the event it actually describes, instead of leaving it a separate,
 * disconnected tool the user has to go find. Only works for the circuits
 * and years (2022-2025) that have a trained model (see predict_service.py's
 * CIRCUITS registry) — everything else gets an honest "not available yet",
 * not a silent failure. This is a RECONSTRUCTION (built from the session's
 * own real tyres/pit stops/grid), not a forecast made before the session —
 * real forecasts are Phase 4 scope, hence Review staying disabled for now.
 */
export default function PreviewPage() {
  const params = useParams<{ season: string; round: string }>();
  const season = Number(params.season);
  const round = Number(params.round);

  const [eventName, setEventName] = useState<string | null>(null);
  const [circuits, setCircuits] = useState<Circuit[]>([]);
  const [serveYears, setServeYears] = useState<number[]>([]);
  const [resolving, setResolving] = useState(true);

  const [session, setSession] = useState<Session>("race");
  const [profile, setProfile] = useState<CircuitProfile | null>(null);
  const [raceData, setRaceData] = useState<RacePrediction | null>(null);
  const [qualData, setQualData] = useState<QualifyingPrediction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getSchedule(season), getHealth()])
      .then(([evs, health]) => {
        setEventName(evs.find((e) => e.round === round)?.name ?? null);
        setCircuits(health.circuits);
        setServeYears(health.years);
      })
      .catch(() => {
        setEventName(null);
        setCircuits([]);
      })
      .finally(() => setResolving(false));
  }, [season, round]);

  const circuitKey = eventName ? findCircuitKey(circuits, eventName) : null;
  const supported = Boolean(circuitKey) && serveYears.includes(season);

  useEffect(() => {
    if (!circuitKey || !supported) return;
    setLoading(true);
    setError(null);
    getCircuitProfile(circuitKey).then(setProfile).catch(() => setProfile(null));
    const fetcher = session === "race" ? getRacePrediction(circuitKey, season) : getQualifyingPrediction(circuitKey, season);
    fetcher
      .then((data) => (session === "race" ? setRaceData(data as RacePrediction) : setQualData(data as QualifyingPrediction)))
      .catch((e) => setError(e instanceof Error ? e.message : "Prediction failed."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [circuitKey, supported, season, session]);

  if (resolving) {
    return (
      <div className="flex items-center gap-2 text-sm text-black/50 dark:text-white/50">
        <motion.span
          className="inline-block h-3.5 w-3.5 rounded-full border-2 border-accent/30 border-t-accent"
          animate={{ rotate: 360 }}
          transition={{ duration: 0.7, repeat: Infinity, ease: "linear" }}
        />
        Checking model coverage…
      </div>
    );
  }

  if (!supported) {
    return (
      <div className="px-4 py-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 text-sm">
        No trained model for this event yet — reconstructions currently cover 10 circuits
        for 2022-2025. Phase 4 will bring real pre-session forecasts for every event,
        which is the only way to cover 2018-2026 fully.
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-4 mb-6">
        <div className="px-3 py-2 rounded-lg bg-black/5 dark:bg-white/5 text-xs text-black/50 dark:text-white/50 max-w-md">
          Reconstruction built from this session&apos;s own tyres, pit stops and grid —
          not a forecast made before the session. Real forecasts are Phase 4 scope.
        </div>
        <SegmentedControl session={session} onChange={setSession} />
      </div>

      <CircuitProfileCard profile={profile} loading={!profile} showTrackMap={false} />

      {error && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 text-sm">
          {error}
        </div>
      )}

      <AnimatePresence mode="wait">
        {!loading && session === "race" && raceData && (
          <motion.div
            key="race"
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
            key="qual"
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
