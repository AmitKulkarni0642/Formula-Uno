"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { motion } from "motion/react";
import { getSchedule } from "@/lib/api";
import type { ScheduleEvent } from "@/lib/types";

const EASE = [0.16, 1, 0.3, 1] as const;
const YEARS = Array.from({ length: 2026 - 2018 + 1 }, (_, i) => 2026 - i);

export default function SeasonPage() {
  const params = useParams<{ season: string }>();
  const router = useRouter();
  const season = Number(params.season);

  const [events, setEvents] = useState<ScheduleEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getSchedule(season)
      .then(setEvents)
      .catch(() => setError("Couldn't load this season's calendar."))
      .finally(() => setLoading(false));
  }, [season]);

  return (
    <div className="min-h-screen max-w-4xl mx-auto px-4 py-8 sm:px-6">
      <motion.header
        className="mb-8 flex items-start justify-between flex-wrap gap-4"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <div>
          <p className="text-xs tracking-widest uppercase text-accent font-semibold mb-1">
            Formula Uno
          </p>
          <h1 className="text-3xl font-display font-bold tracking-tight">{season} season</h1>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="rounded-lg border border-black/15 dark:border-white/15 bg-transparent px-3 py-1.5 text-sm"
            value={season}
            onChange={(e) => router.push(`/${e.target.value}`)}
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <Link href="/" className="text-sm text-black/50 dark:text-white/50 hover:text-black dark:hover:text-white transition-colors">
            ← Predictions
          </Link>
        </div>
      </motion.header>

      {error && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-black/50 dark:text-white/50">
          <motion.span
            className="inline-block h-3.5 w-3.5 rounded-full border-2 border-accent/30 border-t-accent"
            animate={{ rotate: 360 }}
            transition={{ duration: 0.7, repeat: Infinity, ease: "linear" }}
          />
          Loading calendar…
        </div>
      ) : (
        <motion.div
          className="flex flex-col divide-y divide-black/5 dark:divide-white/5 rounded-xl border border-black/10 dark:border-white/10 overflow-hidden"
          initial="hidden"
          animate="show"
          variants={{ show: { transition: { staggerChildren: 0.03 } } }}
        >
          {events.map((ev) => (
            <motion.div
              key={ev.round}
              variants={{ hidden: { opacity: 0, x: -6 }, show: { opacity: 1, x: 0 } }}
              transition={{ duration: 0.3, ease: EASE }}
            >
              <Link
                href={`/${season}/${ev.round}`}
                className="flex items-center gap-4 px-4 py-3 hover:bg-black/[0.03] dark:hover:bg-white/[0.03] transition-colors"
              >
                <span className="font-mono text-xs text-black/40 dark:text-white/40 tabular-nums w-8">
                  R{ev.round}
                </span>
                <span className="font-medium flex-1">{ev.name}</span>
                <span className="text-sm text-black/40 dark:text-white/40">{ev.location}</span>
              </Link>
            </motion.div>
          ))}
        </motion.div>
      )}
    </div>
  );
}
