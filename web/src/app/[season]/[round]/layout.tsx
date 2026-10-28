"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { getSchedule, getTrackMapForYear } from "@/lib/api";
import type { ScheduleEvent, TrackMapData } from "@/lib/types";
import TrackMap from "@/components/TrackMap";

const EASE = [0.16, 1, 0.3, 1] as const;

const TABS = [
  { slug: "preview", label: "Preview", disabled: true },
  { slug: "quali", label: "Quali", disabled: false },
  { slug: "race", label: "Race", disabled: false },
  { slug: "review", label: "Review", disabled: true },
] as const;

export default function EventLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ season: string; round: string }>();
  const pathname = usePathname();
  const season = Number(params.season);
  const round = Number(params.round);
  const activeTab = pathname.split("/")[3] ?? "quali";

  const [event, setEvent] = useState<ScheduleEvent | null>(null);
  const [trackMap, setTrackMap] = useState<TrackMapData | null>(null);
  const [trackMapLoading, setTrackMapLoading] = useState(true);
  const trackMapCache = useRef(new Map<string, TrackMapData>());

  useEffect(() => {
    getSchedule(season)
      .then((evs) => setEvent(evs.find((e) => e.round === round) ?? null))
      .catch(() => setEvent(null));
  }, [season, round]);

  useEffect(() => {
    if (!event) return;
    const key = `${season}|${event.name}`;
    const cached = trackMapCache.current.get(key);
    if (cached) {
      setTrackMap(cached);
      setTrackMapLoading(false);
      return;
    }
    setTrackMapLoading(true);
    getTrackMapForYear(season, event.name)
      .then((tm) => {
        trackMapCache.current.set(key, tm);
        setTrackMap(tm);
      })
      .catch(() => setTrackMap(null))
      .finally(() => setTrackMapLoading(false));
  }, [season, event]);

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-4 py-8 sm:px-6">
      <motion.header
        className="mb-6 flex items-start justify-between flex-wrap gap-4"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <div>
          <p className="text-xs tracking-widest uppercase text-accent font-semibold mb-1">
            Formula Uno
          </p>
          <h1 className="text-3xl font-display font-bold tracking-tight">
            {event ? event.name : `Round ${round}`}
          </h1>
          <p className="text-sm text-black/50 dark:text-white/50 mt-1">
            {season} · Round {round}{event ? ` · ${event.location}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <Link href={`/${season}`} className="text-sm text-black/50 dark:text-white/50 hover:text-black dark:hover:text-white transition-colors">
            ← {season} season
          </Link>
          <Link href="/" className="text-sm text-black/50 dark:text-white/50 hover:text-black dark:hover:text-white transition-colors">
            Predictions
          </Link>
        </div>
      </motion.header>

      <div className="flex gap-1 mb-6 p-1 rounded-lg bg-black/5 dark:bg-white/5 w-fit">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.slug;
          const content = (
            <span
              className={`px-3.5 py-1.5 rounded-md text-sm font-medium transition-colors block ${
                tab.disabled
                  ? "text-black/25 dark:text-white/25 cursor-not-allowed"
                  : isActive
                  ? "bg-white dark:bg-black shadow-sm text-black dark:text-white"
                  : "text-black/50 dark:text-white/50 hover:text-black dark:hover:text-white"
              }`}
            >
              {tab.label}
              {tab.disabled && <span className="ml-1 text-[10px] align-top">soon</span>}
            </span>
          );
          return tab.disabled ? (
            <div key={tab.slug} title="Needs Phase 4's forecasting models — not built yet">{content}</div>
          ) : (
            <Link key={tab.slug} href={`/${season}/${round}/${tab.slug}`}>{content}</Link>
          );
        })}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={`${season}-${round}`}
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3, ease: EASE }}
          className="relative mb-8 h-[22rem] sm:h-[26rem] rounded-2xl border border-black/10 dark:border-white/10 overflow-hidden bg-gradient-to-br from-black/[0.03] to-transparent dark:from-white/[0.03]"
        >
          {trackMapLoading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <motion.div
                className="h-10 w-10 rounded-full border-2 border-accent/25 border-t-accent"
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
        </motion.div>
      </AnimatePresence>

      {children}
    </div>
  );
}
