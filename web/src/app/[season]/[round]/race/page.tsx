"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { ApiError, getRaceComparison, getSchedule, getSessionDrivers } from "@/lib/api";
import type { RaceComparison, SessionDriver } from "@/lib/types";
import RaceCompareChart from "@/components/RaceCompareChart";

const EASE = [0.16, 1, 0.3, 1] as const;

/** Head-to-head pair lives in one URL param (?h2h=a,b of driver_id slugs) per the plan's scheme. */
function parseH2H(sp: URLSearchParams): [string, string] {
  const raw = sp.get("h2h") ?? "";
  const [a = "", b = ""] = raw.split(",");
  return [a, b];
}

export default function RacePage() {
  const params = useParams<{ season: string; round: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const season = Number(params.season);
  const round = Number(params.round);
  const sessionId = `${season}-${String(round).padStart(2, "0")}-R`;

  const [eventName, setEventName] = useState<string | null>(null);
  const [drivers, setDrivers] = useState<SessionDriver[]>([]);
  const [driversLoading, setDriversLoading] = useState(true);
  const [rosterError, setRosterError] = useState<string | null>(null);

  const [driverA, driverB] = parseH2H(searchParams);

  const [data, setData] = useState<RaceComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  function setH2H(a: string, b: string) {
    const sp = new URLSearchParams(searchParams);
    sp.set("h2h", `${a},${b}`);
    router.replace(`?${sp.toString()}`, { scroll: false });
  }

  useEffect(() => {
    getSchedule(season)
      .then((evs) => setEventName(evs.find((e) => e.round === round)?.name ?? null))
      .catch(() => setEventName(null));
  }, [season, round]);

  useEffect(() => {
    if (!eventName) return;
    setDriversLoading(true);
    setRosterError(null);
    getSessionDrivers(season, eventName, "R")
      .then((roster) => {
        setDrivers(roster);
        if (!driverA || !roster.some((d) => d.driver_id === driverA)) {
          setH2H(roster[0]?.driver_id ?? "", roster[1]?.driver_id ?? "");
        }
      })
      .catch((e) => {
        setDrivers([]);
        setRosterError(e instanceof Error ? e.message : "Couldn't load this session's roster.");
      })
      .finally(() => setDriversLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [season, eventName]);

  useEffect(() => {
    if (!driverA || !driverB) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    setData(null);
    getRaceComparison(sessionId, driverA, driverB)
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(e instanceof Error ? e.message : "Comparison failed.");
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, driverA, driverB]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-4 mb-8 pb-6 border-b border-black/10 dark:border-white/10">
        <Field label="Driver A">
          <select
            className="w-48 rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
            value={driverA}
            disabled={driversLoading || drivers.length === 0}
            onChange={(e) => setH2H(e.target.value, driverB)}
          >
            {drivers.map((d) => (
              <option key={d.driver_id} value={d.driver_id}>{d.code} — {d.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Driver B">
          <select
            className="w-48 rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
            value={driverB}
            disabled={driversLoading || drivers.length === 0}
            onChange={(e) => setH2H(driverA, e.target.value)}
          >
            {drivers.map((d) => (
              <option key={d.driver_id} value={d.driver_id}>{d.code} — {d.name}</option>
            ))}
          </select>
        </Field>
        {rosterError && <p className="text-xs text-amber-600 dark:text-amber-400">{rosterError}</p>}
        {!rosterError && (
          <p className="text-xs text-black/40 dark:text-white/40">
            First request for this race ingests it (~15-30s); instant after.
          </p>
        )}
      </div>

      <AnimatePresence>
        {loading && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex items-center gap-2 text-sm text-black/50 dark:text-white/50 mb-6"
          >
            <motion.span
              className="inline-block h-3.5 w-3.5 rounded-full border-2 border-driver-a/30 border-t-driver-a"
              animate={{ rotate: 360 }} transition={{ duration: 0.7, repeat: Infinity, ease: "linear" }}
            />
            Fetching race data…
          </motion.div>
        )}
      </AnimatePresence>

      {notFound && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 text-sm">
          This race session isn&apos;t available — a very old/unsupported event, or this driver didn&apos;t take part.
        </div>
      )}
      {error && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 text-sm">
          {error}
        </div>
      )}

      {data && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: EASE }}>
          <div className="flex items-center gap-3 mb-4 text-sm flex-wrap">
            <span className="font-semibold text-driver-a">{data.driver_a}</span>
            <span className="text-black/40 dark:text-white/40">vs</span>
            <span className="font-semibold text-driver-b">{data.driver_b}</span>
            {data.final_gap_s !== null && (
              <span className="text-black/50 dark:text-white/50">
                — {data.final_gap_s > 0 ? data.driver_a : data.driver_b} ahead by{" "}
                {Math.abs(data.final_gap_s).toFixed(1)}s after {data.laps_compared} laps
              </span>
            )}
          </div>

          {data.laps_compared < data.laps_available.length && (
            <div className="mb-6 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 text-xs">
              Comparison stops at lap {data.laps_compared} of {data.laps_available.length} — one driver
              is missing a lap time after that point (DNF or a data gap).
            </div>
          )}

          {data.lead_changes.length > 0 && (
            <div className="mb-8 rounded-xl border border-black/10 dark:border-white/10 p-4">
              <p className="text-xs uppercase tracking-wide text-black/50 dark:text-white/50 mb-2">Lead changes</p>
              <ul className="space-y-1.5 text-sm">
                {data.lead_changes.map((lc, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-black/30 dark:text-white/30">·</span>
                    Lap {lc.lap_number}: {lc.gap_s > 0 ? data.driver_a : data.driver_b} takes the gap
                    (now {Math.abs(lc.gap_s).toFixed(1)}s ahead)
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mb-8 rounded-xl border border-black/10 dark:border-white/10 p-4">
            <RaceCompareChart data={data} />
          </div>
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
