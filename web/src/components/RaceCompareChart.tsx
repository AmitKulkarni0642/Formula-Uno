"use client";

import ReactECharts from "echarts-for-react";
import type { RaceComparison, RaceStint } from "@/lib/types";
import { formatLapTime } from "@/lib/format";

const COLOR_A = "#E10600";
const COLOR_B = "#1F77B4";
const GAP_COLOR = "#A855F7";

// Real F1 broadcast tyre-compound colors.
const COMPOUND_COLORS: Record<string, string> = {
  SOFT: "#DA291C",
  MEDIUM: "#FFD12E",
  HARD: "#F2F2F2",
  INTERMEDIATE: "#43B02A",
  WET: "#0067AD",
};

function compoundColor(c: string | null): string {
  return (c && COMPOUND_COLORS[c]) || "#999999";
}

/**
 * Whole-race, lap-by-lap view, three stacked panels sharing a lap x-axis:
 * (1) cumulative gap evolution (like a broadcast "race trace") — positive
 * means driver A is ahead on time, with pit stops marked as dotted vertical
 * lines and lead changes as diamond markers; (2) the raw lap-time pace that
 * drove it; (3) actual running position, inverted so P1 sits at the top,
 * drawn as a step line since position only changes at discrete lap
 * boundaries. Tyre stints are listed below rather than charted as a fourth
 * panel: compound + lap range + pace says more at a glance than a color band.
 */
export default function RaceCompareChart({ data }: { data: RaceComparison }) {
  const laps = data.laps;
  if (laps.length === 0) return null;
  const lastLap = laps[laps.length - 1].lap_number;

  const gapSeries = laps.map((l) => [l.lap_number, l.gap_s]);
  const lapTimeA = laps.map((l) => [l.lap_number, l.lap_time_a_s]);
  const lapTimeB = laps.map((l) => [l.lap_number, l.lap_time_b_s]);
  const positionA = laps.filter((l) => l.position_a != null).map((l) => [l.lap_number, l.position_a]);
  const positionB = laps.filter((l) => l.position_b != null).map((l) => [l.lap_number, l.position_b]);
  const positions = laps.flatMap((l) => [l.position_a, l.position_b]).filter((p): p is number => p != null);
  const maxPosition = positions.length ? Math.max(...positions) : 20;
  const pitLapsA = laps.filter((l) => l.pit_lap_a).map((l) => l.lap_number);
  const pitLapsB = laps.filter((l) => l.pit_lap_b).map((l) => l.lap_number);

  // Three stacked panels sharing a lap-number x-axis: gap evolution, raw lap
  // time (the pace that drove the gap), and running position (who's actually
  // ahead on track, inverted so P1 sits at the top like a broadcast chart).
  const rows: [number, number][] = [[4, 30], [40, 22], [68, 24]];

  const option = {
    animation: false,
    textStyle: { fontFamily: "inherit" },
    grid: rows.map(([top, height]) => ({ left: 56, right: 24, top: `${top}%`, height: `${height}%` })),
    xAxis: rows.map((_, i) => ({
      type: "value",
      gridIndex: i,
      min: 1,
      max: lastLap,
      axisLabel: { show: i === rows.length - 1, formatter: (v: number) => `L${Math.round(v)}` },
      axisLine: { show: i === rows.length - 1 },
      splitLine: { show: false },
    })),
    yAxis: [
      {
        gridIndex: 0, name: "Gap (s)", nameTextStyle: { fontSize: 10 }, nameLocation: "middle", nameGap: 42,
        splitLine: { lineStyle: { opacity: 0.08 } }, axisLabel: { fontSize: 10 },
      },
      {
        gridIndex: 1, name: "Lap time", nameTextStyle: { fontSize: 10 }, nameLocation: "middle", nameGap: 42,
        splitLine: { lineStyle: { opacity: 0.08 } },
        axisLabel: { fontSize: 10, formatter: (v: number) => formatLapTime(v) },
      },
      {
        gridIndex: 2, name: "Position", nameTextStyle: { fontSize: 10 }, nameLocation: "middle", nameGap: 42,
        inverse: true, min: 1, max: maxPosition, interval: 1,
        splitLine: { lineStyle: { opacity: 0.08 } }, axisLabel: { fontSize: 10, formatter: (v: number) => `P${v}` },
      },
    ],
    axisPointer: { link: [{ xAxisIndex: "all" }], label: { show: false } },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line" },
      formatter: (params: { seriesName: string; seriesIndex: number; data: [number, number] }[]) => {
        if (!params?.length) return "";
        const lap = Math.round(params[0].data[0]);
        const lines = params.map((p) => {
          if (p.seriesIndex === 0) return `${p.seriesName}: ${p.data[1] >= 0 ? "+" : ""}${p.data[1].toFixed(2)}s`;
          if (p.seriesIndex === 1 || p.seriesIndex === 2) return `${p.seriesName}: ${formatLapTime(p.data[1])}`;
          return `${p.seriesName}: P${Math.round(p.data[1])}`;
        });
        return [`Lap ${lap}`, ...lines].join("<br/>");
      },
    },
    series: [
      {
        name: "Gap", type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
        data: gapSeries, color: GAP_COLOR, lineStyle: { width: 1.8 }, areaStyle: { opacity: 0.08 },
        markLine: {
          silent: true, symbol: "none",
          data: [
            { yAxis: 0, lineStyle: { color: "#888", type: "dashed", width: 1 } },
            ...pitLapsA.map((lap) => ({ xAxis: lap, lineStyle: { color: COLOR_A, type: "dotted", width: 1.5, opacity: 0.7 } })),
            ...pitLapsB.map((lap) => ({ xAxis: lap, lineStyle: { color: COLOR_B, type: "dotted", width: 1.5, opacity: 0.7 } })),
          ],
        },
        markPoint: {
          symbol: "diamond", symbolSize: 10, silent: true,
          data: data.lead_changes.map((lc) => ({ coord: [lc.lap_number, lc.gap_s] })),
          itemStyle: { color: "#111827", borderColor: "#fff", borderWidth: 1 },
          label: { show: false },
        },
      },
      {
        name: data.driver_a, type: "line", xAxisIndex: 1, yAxisIndex: 1, showSymbol: false,
        data: lapTimeA, color: COLOR_A, lineStyle: { width: 1.2 },
      },
      {
        name: data.driver_b, type: "line", xAxisIndex: 1, yAxisIndex: 1, showSymbol: false,
        data: lapTimeB, color: COLOR_B, lineStyle: { width: 1.2 },
      },
      {
        // Position only changes at discrete lap boundaries — a step line
        // (not a smooth interpolation) is the honest way to draw that.
        name: data.driver_a, type: "line", step: "end", xAxisIndex: 2, yAxisIndex: 2, showSymbol: false,
        data: positionA, color: COLOR_A, lineStyle: { width: 1.5 }, legendHoverLink: false,
      },
      {
        name: data.driver_b, type: "line", step: "end", xAxisIndex: 2, yAxisIndex: 2, showSymbol: false,
        data: positionB, color: COLOR_B, lineStyle: { width: 1.5 },
      },
    ],
  };

  return (
    <div>
      <ReactECharts option={option} style={{ height: 560, width: "100%" }} opts={{ renderer: "svg" }} notMerge />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mt-4">
        <StintList label={data.driver_a} color={COLOR_A} stints={data.stints_a} />
        <StintList label={data.driver_b} color={COLOR_B} stints={data.stints_b} />
      </div>
      <p className="text-xs text-black/40 dark:text-white/40 mt-4">
        Dotted lines mark pit stops (red = {data.driver_a}, blue = {data.driver_b}); diamonds mark laps
        where the on-track order between them actually flipped.
      </p>
    </div>
  );
}

function StintList({ label, color, stints }: { label: string; color: string; stints: RaceStint[] }) {
  return (
    <div>
      <p className="font-semibold mb-2 text-sm" style={{ color }}>{label}</p>
      <div className="flex flex-col gap-1.5">
        {stints.map((s) => (
          <div key={s.stint} className="flex items-center gap-2 text-xs">
            <span
              className="inline-block h-3 w-3 rounded-full border border-black/25 dark:border-white/30 shrink-0"
              style={{ backgroundColor: compoundColor(s.compound) }}
              title={s.compound ?? "unknown compound"}
            />
            <span className="tabular-nums text-black/60 dark:text-white/60">
              L{s.lap_start}–{s.lap_end} ({s.lap_count}) {s.compound ?? "—"}
              {s.avg_lap_s != null ? ` · ${formatLapTime(s.avg_lap_s)} avg` : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
