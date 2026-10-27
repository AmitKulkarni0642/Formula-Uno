"use client";

import { AnimatePresence, motion, type Variants } from "motion/react";
import TrackMap from "./TrackMap";
import type { CircuitProfile } from "@/lib/types";
import { formatLapTime } from "@/lib/format";

const EASE = [0.16, 1, 0.3, 1] as const;

const container: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } },
};
const item: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE } },
};

export default function CircuitProfileCard({
  profile,
  loading,
}: {
  profile: CircuitProfile | null;
  loading: boolean;
}) {
  return (
    <div className="mb-10 pb-8 border-b border-black/10 dark:border-white/10">
      <AnimatePresence mode="wait">
        {loading || !profile ? (
          <motion.div
            key="skeleton"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-6"
          >
            <div className="aspect-square rounded-xl bg-black/5 dark:bg-white/5 animate-pulse" />
            <div className="space-y-3">
              <div className="h-5 w-56 rounded bg-black/5 dark:bg-white/5 animate-pulse" />
              <div className="h-3 w-full rounded bg-black/5 dark:bg-white/5 animate-pulse" />
              <div className="h-3 w-3/4 rounded bg-black/5 dark:bg-white/5 animate-pulse" />
            </div>
          </motion.div>
        ) : (
          <motion.div
            key={profile.nickname}
            variants={container}
            initial="hidden"
            animate="show"
            className="grid grid-cols-1 sm:grid-cols-[180px_1fr] gap-6"
          >
            <motion.div variants={item} className="aspect-square">
              {profile.track_map ? (
                <TrackMap points={profile.track_map} />
              ) : (
                <div className="w-full h-full rounded-xl border border-dashed border-black/15 dark:border-white/15 flex items-center justify-center text-xs text-black/40 dark:text-white/40 text-center p-4">
                  Track map unavailable
                  <br />
                  (no mirrored telemetry)
                </div>
              )}
            </motion.div>

            <div>
              <motion.h2 variants={item} className="text-lg font-semibold mb-1.5">
                {profile.nickname}
              </motion.h2>

              {profile.tags.length > 0 && (
                <motion.div variants={item} className="flex flex-wrap gap-1.5 mb-3">
                  {profile.tags.map((t) => (
                    <span
                      key={t}
                      className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300"
                    >
                      {t}
                    </span>
                  ))}
                </motion.div>
              )}

              {profile.history && (
                <motion.p variants={item} className="text-sm text-black/60 dark:text-white/60 mb-4 max-w-prose">
                  {profile.history}
                </motion.p>
              )}

              <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <Fact
                  label="Last winner (2025)"
                  value={
                    profile.last_winner
                      ? `${profile.last_winner.driver} (${profile.last_winner.team})`
                      : "—"
                  }
                />
                <Fact
                  label="Fastest race lap (2022–25)"
                  value={
                    profile.fastest_race_lap ? formatLapTime(profile.fastest_race_lap.time_s) : "—"
                  }
                  hint={
                    profile.fastest_race_lap
                      ? `${profile.fastest_race_lap.driver} (${profile.fastest_race_lap.team}), ${profile.fastest_race_lap.year}`
                      : undefined
                  }
                />
                <Fact
                  label="Fastest qualifying lap (2022–25)"
                  value={
                    profile.fastest_qualifying_lap
                      ? formatLapTime(profile.fastest_qualifying_lap.time_s)
                      : "—"
                  }
                  hint={
                    profile.fastest_qualifying_lap
                      ? `${profile.fastest_qualifying_lap.driver} (${profile.fastest_qualifying_lap.team}), ${profile.fastest_qualifying_lap.year}`
                      : undefined
                  }
                />
              </motion.div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div
      className="rounded-lg border border-black/10 dark:border-white/10 px-3 py-2"
      title={hint}
    >
      <p className="text-[10px] uppercase tracking-wide text-black/50 dark:text-white/50 mb-0.5">
        {label}
      </p>
      <p className="text-sm font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-[10px] text-black/40 dark:text-white/40 truncate mt-0.5">{hint}</p>}
    </div>
  );
}
