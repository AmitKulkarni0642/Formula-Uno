"""
Distance-aligns two laps so they're comparable point-for-point.

FastF1's Distance channel is the integral of ~4 Hz speed samples, which
drifts 0.5-1% over a lap. Without correction, two laps would end at
different measured lengths, so a corner marked at e.g. 350m would land at a
different point on each lap's own grid — comparisons and segmentation would
silently misalign near the end of the lap. Rescaling each lap's distance
axis to a shared reference length fixes that alignment, but it's an honest,
bounded fix, not a perfect one: if the two laps drifted by different
amounts, rescaling re-introduces a small, predictable pace illusion (the
more-compressed lap reads as very slightly faster) roughly equal to the
drift-fraction difference times the lap time — a few hundred ms at most,
not a gap that grows without bound the way *skipping* rescaling would.
"""

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("distance_m", "t_ms", "speed", "throttle", "gear", "brake")


def _rescale_distance(distance: np.ndarray, reference_length: float) -> np.ndarray:
    measured_length = distance[-1]
    if measured_length <= 0:
        return distance
    return distance * (reference_length / measured_length)


def resample_to_grid(tel: pd.DataFrame, grid: np.ndarray) -> dict[str, np.ndarray]:
    """
    tel needs columns: distance_m, t_ms, speed, throttle, gear, brake (bool).
    Everything continuous is linearly interpolated onto `grid`; brake is
    on/off, so it takes the nearest sample instead (no "half-braking").
    """
    d = tel["distance_m"].to_numpy(dtype=float)
    out = {
        "t_ms": np.interp(grid, d, tel["t_ms"].to_numpy(dtype=float)),
        "speed": np.interp(grid, d, tel["speed"].to_numpy(dtype=float)),
        "throttle": np.interp(grid, d, tel["throttle"].to_numpy(dtype=float)),
        "gear": np.interp(grid, d, tel["gear"].to_numpy(dtype=float)),
    }
    nearest_idx = np.clip(np.searchsorted(d, grid), 0, len(d) - 1)
    out["brake"] = tel["brake"].to_numpy(dtype=bool)[nearest_idx]
    return out


def align_laps(tel_a: pd.DataFrame, tel_b: pd.DataFrame, grid_resolution_m: float = 1.0):
    """
    Returns (grid, aligned_a, aligned_b, delta_ms).

    delta_ms[i] = aligned_b["t_ms"][i] - aligned_a["t_ms"][i] at distance
    grid[i] — negative means B is ahead of A at that point on track. Both
    laps' t_ms are expected to start at (or near) 0 at distance 0, so this
    is a genuine cumulative delta-time curve, not just a speed difference.
    """
    missing_a = [c for c in REQUIRED_COLUMNS if c not in tel_a.columns]
    missing_b = [c for c in REQUIRED_COLUMNS if c not in tel_b.columns]
    if missing_a or missing_b:
        raise ValueError(f"missing telemetry columns — a:{missing_a} b:{missing_b}")

    len_a = float(tel_a["distance_m"].iloc[-1])
    len_b = float(tel_b["distance_m"].iloc[-1])
    reference_length = max(len_a, len_b)  # rescale the shorter trace up, not the longer down

    tel_a = tel_a.assign(distance_m=_rescale_distance(tel_a["distance_m"].to_numpy(dtype=float), reference_length))
    tel_b = tel_b.assign(distance_m=_rescale_distance(tel_b["distance_m"].to_numpy(dtype=float), reference_length))

    grid = np.arange(0.0, reference_length, grid_resolution_m)
    a = resample_to_grid(tel_a, grid)
    b = resample_to_grid(tel_b, grid)
    delta_ms = b["t_ms"] - a["t_ms"]
    return grid, a, b, delta_ms


def downsample(grid: np.ndarray, series: dict[str, np.ndarray], delta_ms: np.ndarray, resolution: int):
    """Stride every `resolution`-th sample for display — full-resolution arrays
    are overkill for a browser chart and bloat the response for no visual gain."""
    if resolution <= 1:
        return grid, series, delta_ms
    idx = np.arange(0, len(grid), resolution)
    return grid[idx], {k: v[idx] for k, v in series.items()}, delta_ms[idx]
