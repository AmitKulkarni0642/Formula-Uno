"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "motion/react";
import {
  ApiError, getQualifyingComparison, getSchedule, getSessionDrivers, getTrackMapForYear,
} from "@/lib/api";
import type { ScheduleEvent, SessionDriver, TelemetryComparison, TrackMapData } from "@/lib/types";
import TelemetryCompareChart from "@/components/TelemetryCompareChart";
import TrackMap from "@/components/TrackMap";

const EASE = [0.16, 1, 0.3, 1] as const;
const YEARS = Array.from({ length: 2026 - 2018 + 1 }, (_, i) => 2026 - i); // 2026..2018

export default function ComparePage() {
  const [year, setYear] = useState(2022);
  const [events, setEvents] = useState<ScheduleEvent[]>([]);
  const [event, setEvent] = useState("");
  const [eventsLoading, setEventsLoading] = useState(false);

  const [drivers, setDrivers] = useState<SessionDriver[]>([]);
  const [driverA, setDriverA] = useState("");
  const [driverB, setDriverB] = useState("");
  const [driversLoading, setDriversLoading] = useState(false);
  const [rosterError, setRosterError] = useState<string | null>(null);

  const [trackMap, setTrackMap] = useState<TrackMapData | null>(null);
  const [trackMapLoading, setTrackMapLoading] = useState(false);
  const trackMapCache = useRef(new Map<string, TrackMapData>());

  const [data, setData] = useState<TelemetryComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  // Year changes -> reload the calendar, reset everything downstream.
  useEffect(() => {
    setEventsLoading(true);
    setEvent("");
    setDrivers([]);
    setDriverA("");
    setDriverB("");
    setData(null);
    getSchedule(year)
      .then((evs) => {
        setEvents(evs);
        setEvent(evs[0]?.name ?? "");
      })
      .catch(() => setEvents([]))
      .finally(() => setEventsLoading(false));
  }, [year]);

  // Track changes -> load that session's actual qualifying roster.
  useEffect(() => {
    if (!event) return;
    setDriversLoading(true);
    setRosterError(null);
    setDriverA("");
    setDriverB("");
    setData(null);
    getSessionDrivers(year, event)
      .then((roster) => {
        setDrivers(roster);
        setDriverA(roster[0]?.code ?? "");
        setDriverB(roster[1]?.code ?? "");
      })
      .catch((e) => {
        setDrivers([]);
        setRosterError(e instanceof Error ? e.message : "Couldn't load this session's roster.");
      })
      .finally(() => setDriversLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event, year]);

  // Track changes -> load THIS year's actual layout (circuits do get reprofiled).
  // Cached per (year, event) for the life of the tab: FastF1 has to pull a whole
  // session's telemetry for a fresh track, which is genuinely slow the first time,
  // but there's no reason to pay that cost again when flipping back to a track
  // already seen this session.
  useEffect(() => {
    if (!event) return;
    const key = `${year}|${event}`;
    const cached = trackMapCache.current.get(key);
    if (cached) {
      setTrackMap(cached);
      setTrackMapLoading(false);
      return;
    }
    setTrackMapLoading(true);
    setTrackMap(null);
    getTrackMapForYear(year, event)
      .then((tm) => {
        trackMapCache.current.set(key, tm);
        setTrackMap(tm);
      })
      .catch(() => setTrackMap(null))
      .finally(() => setTrackMapLoading(false));
  }, [event, year]);

  function runComparison() {
    if (!event || !driverA || !driverB) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    setData(null);
    getQualifyingComparison(event, year, driverA, driverB)
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(e instanceof Error ? e.message : "Comparison failed.");
      })
      .finally(() => setLoading(false));
  }

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-4 py-8 sm:px-6">
      <motion.header
        className="mb-8"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <p className="text-xs tracking-widest uppercase text-red-600 font-semibold mb-1">
          Formula Uno
        </p>
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <h1 className="text-3xl font-bold tracking-tight">Qualifying telemetry comparison</h1>
          <Link href="/" className="text-sm text-black/50 dark:text-white/50 hover:text-black dark:hover:text-white transition-colors">
            ← Predictions
          </Link>
        </div>
        <p className="text-sm text-black/50 dark:text-white/50 mt-1">
          Any two drivers&apos; fastest qualifying laps, aligned by distance — real telemetry, not a model prediction.
        </p>
      </motion.header>

      <motion.div
        className="flex flex-wrap items-end gap-4 mb-8 pb-6 border-b border-black/10 dark:border-white/10"
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.08, ease: EASE }}
      >
        <Field label="Year">
          <select
            className="w-24 rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </Field>
        <Field label="Track">
          <select
            className="min-w-[13rem] rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
            value={event}
            disabled={eventsLoading || events.length === 0}
            onChange={(e) => setEvent(e.target.value)}
          >
            {eventsLoading && <option>Loading calendar…</option>}
            {!eventsLoading && events.length === 0 && <option>No events found</option>}
            {events.map((ev) => (
              <option key={ev.round} value={ev.name}>
                R{ev.round} — {ev.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Driver A">
          <select
            className="w-44 rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
            value={driverA}
            disabled={driversLoading || drivers.length === 0}
            onChange={(e) => setDriverA(e.target.value)}
          >
            {driversLoading && <option>Loading roster…</option>}
            {drivers.map((d) => (
              <option key={d.code} value={d.code}>{d.code} — {d.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Driver B">
          <select
            className="w-44 rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
            value={driverB}
            disabled={driversLoading || drivers.length === 0}
            onChange={(e) => setDriverB(e.target.value)}
          >
            {driversLoading && <option>Loading roster…</option>}
            {drivers.map((d) => (
              <option key={d.code} value={d.code}>{d.code} — {d.name}</option>
            ))}
          </select>
        </Field>
        <motion.button
          whileTap={{ scale: 0.96 }}
          onClick={runComparison}
          disabled={!event || !driverA || !driverB || driverA === driverB}
          className="px-4 py-1.5 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors disabled:opacity-40 disabled:hover:bg-red-600"
        >
          Compare
        </motion.button>
        {rosterError ? (
          <p className="text-xs text-amber-600 dark:text-amber-400 basis-full sm:basis-auto">{rosterError}</p>
        ) : (
          <p className="text-xs text-black/40 dark:text-white/40 basis-full sm:basis-auto">
            Every round, every season 2018–2026 — pick a track to load who actually qualified.
          </p>
        )}
      </motion.div>

      <AnimatePresence mode="wait">
        {event && (
          <motion.div
            key={`${year}-${event}`}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
            className="relative mb-8 h-[28rem] sm:h-[32rem] rounded-2xl border border-black/10 dark:border-white/10 overflow-hidden bg-gradient-to-br from-black/[0.03] to-transparent dark:from-white/[0.03]"
          >
            {trackMapLoading ? (
              <div className="absolute inset-0 flex items-center justify-center">
                <motion.div
                  className="h-10 w-10 rounded-full border-2 border-violet-400/25 border-t-violet-400"
                  animate={{ rotate: 360 }}
                  transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }}
                />
              </div>
            ) : trackMap && trackMap.outline.length > 0 ? (
              <TrackMap points={trackMap.outline} corners={trackMap.corners} />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-sm text-black/30 dark:text-white/30">
                No layout available for this session
              </div>
            )}

            <div className="absolute top-3 left-4 pointer-events-none">
              <p className="font-semibold text-sm drop-shadow-sm">{event}</p>
              <p className="text-xs text-black/40 dark:text-white/40">{year}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {loading && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex items-center gap-2 text-sm text-black/50 dark:text-white/50 mb-6"
          >
            <motion.span
              className="inline-block h-3.5 w-3.5 rounded-full border-2 border-red-600/30 border-t-red-600"
              animate={{ rotate: 360 }} transition={{ duration: 0.7, repeat: Infinity, ease: "linear" }}
            />
            Fetching telemetry…
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {notFound && (
          <motion.div
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden mb-6"
          >
            <div className="px-4 py-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 text-sm">
              Telemetry isn&apos;t archived for this specific session/driver — try a different driver pair or
              double-check the driver codes and year.
            </div>
          </motion.div>
        )}
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden mb-6"
          >
            <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 text-sm">
              {error}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {data && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: EASE }}>
          <div className="flex items-center gap-3 mb-4 text-sm flex-wrap">
            <span className="font-semibold" style={{ color: "#E10600" }}>
              {data.driver_a}{" "}
              <span className="font-normal text-black/40 dark:text-white/40">
                {data.position_a ? `(P${data.position_a})` : ""}
              </span>
            </span>
            <span className="text-black/40 dark:text-white/40">vs</span>
            <span className="font-semibold" style={{ color: "#1F77B4" }}>
              {data.driver_b}{" "}
              <span className="font-normal text-black/40 dark:text-white/40">
                {data.position_b ? `(P${data.position_b})` : ""}
              </span>
            </span>
            <span className="text-black/50 dark:text-white/50">
              — {data.total_delta_s < 0 ? data.driver_b : data.driver_a} ahead by {Math.abs(data.total_delta_s).toFixed(3)}s
            </span>
          </div>

          {!data.same_segment && (
            <div className="mb-6 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 text-xs">
              {data.driver_a} and {data.driver_b} set their fastest laps in different segments
              ({data.segment_a} vs {data.segment_b}) — conditions may not be directly comparable.
            </div>
          )}

          {data.insights.length > 0 && (
            <div className="mb-8 rounded-xl border border-black/10 dark:border-white/10 p-4">
              <p className="text-xs uppercase tracking-wide text-black/50 dark:text-white/50 mb-2">
                Where the lap was won and lost
              </p>
              <ul className="space-y-1.5 text-sm">
                {data.insights.map((line, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-black/30 dark:text-white/30">·</span>
                    {line}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mb-8 rounded-xl border border-black/10 dark:border-white/10 p-2">
            <TelemetryCompareChart data={data} />
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-black/50 dark:text-white/50 border-b border-black/10 dark:border-white/10">
                <th className="py-2 pr-3">Corner</th>
                <th className="py-2 pr-3">Distance</th>
                <th className="py-2 pr-3">Time Δ</th>
                <th className="py-2 pr-3">Braking pt Δ</th>
                <th className="py-2 pr-3">Min speed Δ</th>
                <th className="py-2 pr-3">Exit speed Δ</th>
                <th className="py-2 pr-3">Category</th>
              </tr>
            </thead>
            <tbody>
              {data.segments.map((s, i) => (
                <tr key={i} className="border-b border-black/5 dark:border-white/5">
                  <td className="py-1.5 pr-3 tabular-nums">{s.corner ?? "—"}</td>
                  <td className="py-1.5 pr-3 tabular-nums text-black/60 dark:text-white/60">
                    {Math.round(s.start_distance_m)}–{Math.round(s.end_distance_m)}m
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums font-medium">{s.time_delta_s.toFixed(3)}s</td>
                  <td className="py-1.5 pr-3 tabular-nums text-black/60 dark:text-white/60">
                    {s.braking_point_diff_m !== null ? `${s.braking_point_diff_m.toFixed(0)}m` : "—"}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums text-black/60 dark:text-white/60">{s.min_speed_diff_kmh.toFixed(1)} km/h</td>
                  <td className="py-1.5 pr-3 tabular-nums text-black/60 dark:text-white/60">{s.exit_speed_diff_kmh.toFixed(1)} km/h</td>
                  <td className="py-1.5 pr-3 capitalize text-black/60 dark:text-white/60">{s.category}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </motion.div>
      )}
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
