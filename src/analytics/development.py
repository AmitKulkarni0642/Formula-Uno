"""
Development-race analysis.

Measures a team's qualifying pace RELATIVE to pole across a season, then locates
step-changes (shifts in the mean gap) with change-point detection.

Two deliberate design choices:
  1. It uses ACTUAL qualifying results from FastF1 — it is independent of the
     lap-time prediction models. This is the pure data-analysis pillar.
  2. Change-point detection is implemented directly in NumPy rather than pulling
     a library. For a "change in mean" signal this is the standard least-squares
     method, and it keeps the logic transparent and dependency-free.
"""

import fastf1
import numpy as np
import pandas as pd

from src.ingestion.load_session import load_qualifying

WET = {"INTERMEDIATE", "WET"}


# ── The pace signal ───────────────────────────────────────────────────────────

def season_gap_to_pole(year: int, team: str) -> pd.DataFrame:
    """
    For every race in a season, compute `team`'s best DRY qualifying lap and its
    gap to pole (the fastest car). Relative pace normalises away the track/tyre/
    fuel confounds, so the gap is comparable race to race.

    Returns rows: round, event, pole_s, team_s, gap_s.
    Rounds with no dry team lap (wet session, cancelled, DNS) are skipped.
    """
    schedule = fastf1.get_event_schedule(year, include_testing=False)
    rows = []
    for _, ev in schedule.iterrows():
        rnd = int(ev["RoundNumber"])
        if rnd == 0:
            continue
        try:
            laps = load_qualifying(year, rnd)["laps"].copy()
        except Exception:
            continue  # session not available / cancelled
        laps["s"] = laps["LapTime"].dt.total_seconds()
        dry = laps[laps["IsAccurate"] & ~laps["Compound"].isin(WET) & laps["s"].notna()]
        if dry.empty:
            continue
        team_laps = dry[dry["Team"] == team]["s"]
        if team_laps.empty:
            continue
        pole = dry["s"].min()
        team_best = team_laps.min()
        rows.append({
            "round":  rnd,
            "event":  str(ev["EventName"]),
            "pole_s": round(float(pole), 3),
            "team_s": round(float(team_best), 3),
            "gap_s":  round(float(team_best - pole), 3),
        })
    return pd.DataFrame(rows)


# ── Change-point detection (change in mean, least squares) ──────────────────────

def _segment_cost(x: np.ndarray) -> float:
    """Sum of squared deviations from the segment mean (the l2 cost of one mean)."""
    return float(((x - x.mean()) ** 2).sum()) if len(x) else 0.0


def best_single_changepoint(values, min_size: int = 2):
    """
    Find the single split that best explains a change in mean, by minimising the
    total within-segment squared error. The split is BEFORE the returned index
    (segment A = values[:i], segment B = values[i:]).

    Returns (index, variance_explained_fraction). index is None if no split helps.
    """
    x = np.asarray(values, dtype=float)
    n = len(x)
    total = _segment_cost(x)
    best_i, best_cost = None, total
    for i in range(min_size, n - min_size + 1):
        cost = _segment_cost(x[:i]) + _segment_cost(x[i:])
        if cost < best_cost:
            best_cost, best_i = cost, i
    frac = (1.0 - best_cost / total) if total > 0 else 0.0
    return best_i, frac


def binary_segmentation(values, max_bkps: int = 3, min_frac: float = 0.10, min_size: int = 2):
    """
    Find multiple change-points by recursively splitting (binary segmentation).
    A split is kept only if it explains at least `min_frac` of the segment's
    variance. Returns a sorted list of change-point indices.
    """
    x = np.asarray(values, dtype=float)
    bkps: list[int] = []

    def _recurse(start: int, end: int) -> None:
        if len(bkps) >= max_bkps or (end - start) < 2 * min_size:
            return
        i, frac = best_single_changepoint(x[start:end], min_size=min_size)
        if i is None or frac < min_frac:
            return
        cp = start + i
        bkps.append(cp)
        _recurse(start, cp)
        _recurse(cp, end)

    _recurse(0, len(x))
    return sorted(bkps)
