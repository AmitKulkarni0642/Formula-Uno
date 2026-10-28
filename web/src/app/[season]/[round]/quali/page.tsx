"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { ApiError, getQualifyingComparison, getSchedule, getSessionDrivers } from "@/lib/api";
import type { SessionDriver, TelemetryComparison } from "@/lib/types";
import TelemetryCompareChart from "@/components/TelemetryCompareChart";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * Driver pair lives in the URL (?a=HAM&b=VER) so a comparison is shareable
 * and survives a refresh — same idea as the plan's ?a=&b=&la=&lb= scheme,
 * minus la/lb: /compare/qualifying only ever compares each driver's single
 * best-segment lap, there's no lap-selection parameter to expose yet.
 */
export default function QualiPage() {
  const params = useParams<{ season: string; round: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const season = Number(params.season);
  const round = Number(params.round);

  const [eventName, setEventName] = useState<string | null>(null);
  const [drivers, setDrivers] = useState<SessionDriver[]>([]);
  const [driversLoading, setDriversLoading] = useState(true);
  const [rosterError, setRosterError] = useState<string | null>(null);

  const driverA = searchParams.get("a") ?? "";
  const driverB = searchParams.get("b") ?? "";

  const [data, setData] = useState<TelemetryComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  function setDriverPair(a: string, b: string) {
    const sp = new URLSearchParams(searchParams);
    sp.set("a", a);
    sp.set("b", b);
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
    getSessionDrivers(season, eventName, "Q")
      .then((roster) => {
        setDrivers(roster);
        if (!driverA || !roster.some((d) => d.code === driverA)) {
          setDriverPair(roster[0]?.code ?? "", roster[1]?.code ?? "");
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
    if (!eventName || !driverA || !driverB) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    setData(null);
    getQualifyingComparison(eventName, season, driverA, driverB)
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(e instanceof Error ? e.message : "Comparison failed.");
      })
      .finally(() => setLoading(false));
  }, [eventName, season, driverA, driverB]);

  return (
    <div>
      <div className="flex flex-wrap items-end gap-4 mb-8 pb-6 border-b border-black/10 dark:border-white/10">
        <Field label="Driver A">
          <select
            className="w-44 rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm disabled:opacity-50"
            value={driverA}
            disabled={driversLoading || drivers.length === 0}
            onChange={(e) => setDriverPair(e.target.value, driverB)}
          >
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
            onChange={(e) => setDriverPair(driverA, e.target.value)}
          >
            {drivers.map((d) => (
              <option key={d.code} value={d.code}>{d.code} — {d.name}</option>
            ))}
          </select>
        </Field>
        {rosterError && <p className="text-xs text-amber-600 dark:text-amber-400">{rosterError}</p>}
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
            Fetching telemetry…
          </motion.div>
        )}
      </AnimatePresence>

      {notFound && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 text-sm">
          Telemetry isn&apos;t archived for this specific session/driver — try a different driver pair.
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
            <span className="font-semibold text-driver-a">
              {data.driver_a}{" "}
              <span className="font-normal text-black/40 dark:text-white/40">
                {data.position_a ? `(P${data.position_a})` : ""}
              </span>
            </span>
            <span className="text-black/40 dark:text-white/40">vs</span>
            <span className="font-semibold text-driver-b">
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
