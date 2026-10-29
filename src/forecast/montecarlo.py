"""
Monte Carlo race forecaster: turns the trained race/quali NNs' pace
predictions into a probability distribution over finishing order for an
event that hasn't happened yet, instead of one deterministic guess.

Per PLAN.md section 7: the race NN is called ONCE per driver per candidate
strategy to get a pace curve (not per Monte Carlo trial -- that would mean
thousands of NN forward passes per driver). Everything that varies trial to
trial (strategy choice, DNFs, safety cars, lap-to-lap noise) is then plain
vectorised NumPy over those precomputed curves.

Every probability used here (stop-count distribution, DNF rate, safety-car
rate, pit loss, lap-to-lap noise) is measured from this circuit's own real
historical data, not assumed -- same "computed from our own historical data
rather than assumed" discipline as predict_service.py's estimate_pit_loss.
"""

import numpy as np
import pandas as pd

from src.ingestion.load_session import load_race
from src.store.ids import team_lineage_id

RNG_DEFAULT_SEED = 42


def historical_stop_counts(circuit_events: pd.DataFrame) -> dict[int, float]:
    """
    Probability of each stop count (1, 2, 3...) at this circuit, from how many
    times a driver actually pitted in its past races. Falls back to a plain
    1-stop certainty if there's no history at all (a brand-new circuit).
    """
    counts: list[int] = []
    for _, ev in circuit_events.iterrows():
        try:
            laps = load_race(int(ev["Season"]), int(ev["Round"]))["laps"]
        except Exception:
            continue
        for _, g in laps.groupby("Driver"):
            counts.append(int(g["PitInTime"].notna().sum()))
    counts = [c for c in counts if c >= 1]  # drivers with 0 recorded stops are usually a DNF-before-ever-stopping
    if not counts:
        return {1: 1.0}
    s = pd.Series(counts)
    dist = (s.value_counts(normalize=True)).to_dict()
    return {int(k): float(v) for k, v in dist.items()}


def team_dnf_rates(recent_events: pd.DataFrame) -> tuple[dict[str, float], float]:
    """
    Per-team (lineage-mapped) fraction of entries that didn't finish, pooled
    across `recent_events`. Returns (per-team rates, grid-average rate) --
    the average is the fallback for a team with too few recent entries to
    trust its own rate (e.g. brand new, like Cadillac in 2026).
    """
    rows = []
    for _, ev in recent_events.iterrows():
        try:
            results = load_race(int(ev["Season"]), int(ev["Round"]))["results"]
        except Exception:
            continue
        for _, r in results.iterrows():
            rows.append({"team": team_lineage_id(str(r["TeamName"])), "dnf": r["Status"] not in ("Finished", "Lapped")})
    if not rows:
        return {}, 0.05
    df = pd.DataFrame(rows)
    overall = float(df["dnf"].mean())
    per_team = df.groupby("team")["dnf"].mean().to_dict()
    counts = df.groupby("team").size().to_dict()
    # Shrink teams with few entries toward the grid average rather than trusting a noisy small sample.
    shrunk = {team: _shrink_toward_pool(rate, counts[team], overall) for team, rate in per_team.items()}
    return shrunk, overall


def _race_had_sc(season: int, round_: int) -> bool | None:
    try:
        laps = load_race(season, round_)["laps"]
    except Exception:
        return None
    if "TrackStatus" not in laps.columns:
        return None
    ts = laps["TrackStatus"].astype(str)
    return bool((ts.str.contains("4") | ts.str.contains("6")).any())


def _shrink_toward_pool(sample_rate: float, n: int, pooled_rate: float, pseudo_count: int = 5) -> float:
    """Pure shrinkage math, split out so it's unit-testable without network."""
    return float((sample_rate * n + pooled_rate * pseudo_count) / (n + pseudo_count))


def safety_car_probability(circuit_events: pd.DataFrame, pooled_events: pd.DataFrame | None = None) -> float:
    """
    Fraction of this circuit's past races with at least one SC/VSC period,
    shrunk toward a broader (pooled_events, e.g. recent seasons across every
    circuit) rate -- same reason as team_dnf_rates' shrinkage: a circuit with
    only 3-4 historical races can easily show an empirical rate of exactly
    0.0 or 1.0 by chance, and treating that as genuine certainty would make
    every single Monte Carlo trial either apply or skip the SC compression,
    collapsing a real source of race-to-race variance into a non-variable.
    """
    had_sc = [_race_had_sc(int(ev["Season"]), int(ev["Round"])) for _, ev in circuit_events.iterrows()]
    had_sc = [h for h in had_sc if h is not None]

    pooled_rate = 0.5  # generic prior if there's truly nothing to pool from either
    if pooled_events is not None and len(pooled_events):
        pooled = [_race_had_sc(int(ev["Season"]), int(ev["Round"])) for _, ev in pooled_events.iterrows()]
        pooled = [h for h in pooled if h is not None]
        if pooled:
            pooled_rate = float(np.mean(pooled))

    if not had_sc:
        return pooled_rate
    return _shrink_toward_pool(float(np.mean(had_sc)), len(had_sc), pooled_rate)


def pit_loss_estimate(circuit_events: pd.DataFrame) -> float:
    """Median real time lost to a pit stop at this circuit -- same method as predict_service.estimate_pit_loss."""
    losses = []
    for _, ev in circuit_events.iterrows():
        try:
            laps = load_race(int(ev["Season"]), int(ev["Round"]))["laps"].copy()
        except Exception:
            continue
        laps["sec"] = laps["LapTime"].dt.total_seconds()
        for _, g in laps.groupby("Driver"):
            g = g.sort_values("LapNumber")
            normal_pace = g[g["IsAccurate"]]["sec"].median()
            if pd.isna(normal_pace):
                continue
            for _, row in g[g["PitInTime"].notna()].iterrows():
                out_rows = g[g["LapNumber"] == row["LapNumber"] + 1]
                in_time = row["sec"]
                out_time = out_rows["sec"].iloc[0] if not out_rows.empty else None
                if pd.notna(in_time) and out_time is not None and pd.notna(out_time):
                    loss = (in_time - normal_pace) + (out_time - normal_pace)
                    if 5 < loss < 60:
                        losses.append(loss)
    return float(np.median(losses)) if losses else 23.0


def lap_to_lap_noise_std(circuit_events: pd.DataFrame) -> float:
    """
    Real within-stint lap-time variability at this circuit (driver mistakes,
    traffic, track evolution) -- NOT the model's cross-circuit RMSE, which
    conflates model error with genuine race variance and is far too large to
    use as per-lap simulation noise. Detrends each stint's tyre-age slope
    first so degradation itself isn't counted as "noise".
    """
    residuals = []
    for _, ev in circuit_events.iterrows():
        try:
            laps = load_race(int(ev["Season"]), int(ev["Round"]))["laps"].copy()
        except Exception:
            continue
        laps["sec"] = laps["LapTime"].dt.total_seconds()
        clean = laps[laps["IsAccurate"] & laps["sec"].notna() & laps["TyreLife"].notna()]
        for _, g in clean.groupby(["Driver", "Stint"]):
            if len(g) < 5:
                continue
            x = g["TyreLife"].to_numpy(dtype=float)
            y = g["sec"].to_numpy(dtype=float)
            coef = np.polyfit(x, y, 1)
            residuals.append(y - np.polyval(coef, x))
    if not residuals:
        return 0.4  # a plausible generic value if there's no history to measure from
    return float(np.std(np.concatenate(residuals)))


def simulate_positions(
    pace_curves: dict[str, np.ndarray],
    grid: dict[str, int],
    stop_dist: dict[int, float],
    pit_loss_s: float,
    dnf_rates: dict[str, float],
    overall_dnf_rate: float,
    driver_team: dict[str, str],
    sc_prob: float,
    noise_std: float,
    n_sims: int = 5000,
    seed: int = RNG_DEFAULT_SEED,
) -> pd.DataFrame:
    """
    Vectorised Monte Carlo over `pace_curves` (driver -> array of predicted
    per-lap times, one precomputed curve per driver already reflecting a
    representative strategy). Returns a DataFrame, one row per sim per
    driver, with finishing position and whether that driver finished.
    """
    rng = np.random.default_rng(seed)
    drivers = list(pace_curves.keys())
    n_drivers = len(drivers)
    total_laps = len(next(iter(pace_curves.values())))

    base = np.stack([pace_curves[d] for d in drivers])  # (n_drivers, total_laps)
    noise = rng.normal(0.0, noise_std, size=(n_sims, n_drivers, total_laps))
    lap_times = base[None, :, :] + noise  # (n_sims, n_drivers, total_laps)

    stop_counts = np.array(list(stop_dist.keys()))
    stop_probs = np.array(list(stop_dist.values()))
    stop_probs = stop_probs / stop_probs.sum()
    stops_per_driver = rng.choice(stop_counts, size=(n_sims, n_drivers), p=stop_probs)
    lap_times_total = lap_times.sum(axis=2) + stops_per_driver * pit_loss_s  # (n_sims, n_drivers)

    dnf_p = np.array([dnf_rates.get(driver_team.get(d, ""), overall_dnf_rate) for d in drivers])
    dnf_draw = rng.random(size=(n_sims, n_drivers)) < dnf_p[None, :]
    dnf_lap = rng.integers(1, max(total_laps, 2), size=(n_sims, n_drivers))

    # A safety car bunches the field up: a fraction of the race-long gap gets
    # erased (not all of it -- a real SC doesn't fully reset relative pace,
    # it compresses accumulated time differences for one neutralised window).
    sc_happens = rng.random(size=n_sims) < sc_prob
    sc_compression = 0.6
    field_mean = lap_times_total.mean(axis=1, keepdims=True)
    compressed = field_mean + (lap_times_total - field_mean) * (1 - sc_compression)
    lap_times_total = np.where(sc_happens[:, None], compressed, lap_times_total)

    # Finishing order: classified finishers ranked by total time; DNFs ranked
    # after every finisher, ordered among themselves by laps completed.
    finish_rank_key = np.where(dnf_draw, 1e6 - dnf_lap, lap_times_total)
    order = np.argsort(finish_rank_key, axis=1)
    positions = np.empty_like(order)
    row_idx = np.arange(n_sims)[:, None]
    positions[row_idx, order] = np.arange(1, n_drivers + 1)[None, :]

    rows = []
    for i, d in enumerate(drivers):
        rows.append(pd.DataFrame({
            "sim": np.arange(n_sims), "driver": d,
            "position": positions[:, i], "finished": ~dnf_draw[:, i],
        }))
    return pd.concat(rows, ignore_index=True)


def summarize(sims: pd.DataFrame, grid: dict[str, int]) -> pd.DataFrame:
    """Win/podium/points probabilities and expected position, one row per driver."""
    n_sims = sims["sim"].nunique()
    rows = []
    for driver, g in sims.groupby("driver"):
        rows.append({
            "driver": driver,
            "grid": grid.get(driver),
            "win_prob": float((g["position"] == 1).mean()),
            "podium_prob": float((g["position"] <= 3).mean()),
            "points_prob": float((g["position"] <= 10).mean()),
            "dnf_prob": float((~g["finished"]).mean()),
            "expected_position": float(g["position"].mean()),
        })
    return pd.DataFrame(rows).sort_values("expected_position").reset_index(drop=True)
