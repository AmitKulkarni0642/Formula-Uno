"use client";

import ReactECharts from "echarts-for-react";
import type { TelemetryComparison } from "@/lib/types";

const COLOR_A = "#E10600";
const COLOR_B = "#1F77B4";

const zip = (xs: number[], ys: number[]) => xs.map((x, i) => [x, ys[i]]);
const zipBool = (xs: number[], ys: boolean[]) => xs.map((x, i) => [x, ys[i] ? 1 : 0]);

/**
 * One ECharts instance with 5 vertically stacked grids (speed, throttle, brake,
 * gear, delta-time), all sharing a distance x-axis with a single linked crosshair
 * (axisPointer.link) — hovering anywhere shows the same distance point across
 * every channel at once, same idea as a real telemetry tool's synced cursor.
 */
export default function TelemetryCompareChart({ data }: { data: TelemetryComparison }) {
  const { distance_m, speed_a, speed_b, throttle_a, throttle_b, brake_a, brake_b, gear_a, gear_b, delta_time_s } = data;

  const rows: [number, number, string][] = [
    [8, 20, "Speed (km/h)"],
    [30, 14, "Throttle (%)"],
    [46, 8, "Brake"],
    [56, 8, "Gear"],
    [66, 26, "Delta (s)"],
  ];

  const option = {
    animation: false,
    textStyle: { fontFamily: "inherit" },
    grid: rows.map(([top, height]) => ({ left: 56, right: 24, top: `${top}%`, height: `${height}%` })),
    xAxis: rows.map((_, i) => ({
      type: "value",
      gridIndex: i,
      min: 0,
      max: distance_m[distance_m.length - 1],
      axisLabel: { show: i === rows.length - 1, formatter: (v: number) => `${Math.round(v)}m` },
      axisLine: { show: i === rows.length - 1 },
      splitLine: { show: false },
    })),
    yAxis: rows.map((_, i) => ({
      gridIndex: i,
      name: rows[i][2],
      nameTextStyle: { fontSize: 10 },
      nameLocation: "middle",
      nameGap: 42,
      splitLine: { lineStyle: { opacity: 0.08 } },
      axisLabel: { fontSize: 10 },
      ...(i === 2 ? { min: 0, max: 1, axisLabel: { show: false }, splitNumber: 1 } : {}),
    })),
    axisPointer: { link: [{ xAxisIndex: "all" }], label: { show: false } },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      formatter: (params: { seriesName: string; data: [number, number]; axisValue: number }[]) => {
        if (!params?.length) return "";
        const dist = Math.round(params[0].data[0]);
        const lines = params.map((p) => `${p.seriesName}: ${p.data[1]}`);
        return [`${dist}m`, ...lines].join("<br/>");
      },
    },
    series: [
      { name: data.driver_a, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, data: zip(distance_m, speed_a), color: COLOR_A, lineStyle: { width: 1.5 } },
      { name: data.driver_b, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, data: zip(distance_m, speed_b), color: COLOR_B, lineStyle: { width: 1.5 } },

      { name: data.driver_a, type: "line", xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, data: zip(distance_m, throttle_a), color: COLOR_A, lineStyle: { width: 1.2 }, legendHoverLink: false },
      { name: data.driver_b, type: "line", xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, data: zip(distance_m, throttle_b), color: COLOR_B, lineStyle: { width: 1.2 } },

      { name: data.driver_a, type: "line", xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, step: "end", data: zipBool(distance_m, brake_a), color: COLOR_A, lineStyle: { width: 1.2 }, areaStyle: { opacity: 0.15 } },
      { name: data.driver_b, type: "line", xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, step: "end", data: zipBool(distance_m, brake_b), color: COLOR_B, lineStyle: { width: 1.2 }, areaStyle: { opacity: 0.1 } },

      { name: data.driver_a, type: "line", xAxisIndex: 3, yAxisIndex: 3, showSymbol: false, step: "end", data: zip(distance_m, gear_a), color: COLOR_A, lineStyle: { width: 1.2 } },
      { name: data.driver_b, type: "line", xAxisIndex: 3, yAxisIndex: 3, showSymbol: false, step: "end", data: zip(distance_m, gear_b), color: COLOR_B, lineStyle: { width: 1.2 } },

      {
        name: "Delta", type: "line", xAxisIndex: 4, yAxisIndex: 4, showSymbol: false,
        data: zip(distance_m, delta_time_s), color: "#9333EA", lineStyle: { width: 1.5 },
        areaStyle: { opacity: 0.08 }, markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: "#888", type: "dashed", width: 1 } },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 560, width: "100%" }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
