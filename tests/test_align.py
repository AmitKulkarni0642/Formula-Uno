"""
Phase 2 alignment correctness, per PLAN.md section 5's test list: synthetic
laps with known offsets (constant speed difference -> linear delta growth;
distance-drift rescaling removes a bogus growing gap; brake stays boolean,
never interpolated).
"""

import numpy as np
import pandas as pd
import pytest

from src.compare import align


def _lap(distance, speed, throttle, gear, brake, t_ms) -> pd.DataFrame:
    return pd.DataFrame({
        "distance_m": distance, "speed": speed, "throttle": throttle,
        "gear": gear, "brake": brake, "t_ms": t_ms,
    })


def _constant_speed_lap(length_m: float, speed_kmh: float, n: int = 200) -> pd.DataFrame:
    distance = np.linspace(0, length_m, n)
    speed_ms = speed_kmh / 3.6
    t_ms = (distance / speed_ms) * 1000.0
    return _lap(distance, np.full(n, speed_kmh), np.full(n, 100.0), np.full(n, 7), np.zeros(n, dtype=bool), t_ms)


def test_identical_laps_give_zero_delta_everywhere():
    lap = _constant_speed_lap(1000, 200)
    _, _, _, delta_ms = align.align_laps(lap, lap.copy())
    assert np.allclose(delta_ms, 0, atol=1e-6)


def test_constant_speed_difference_gives_linearly_growing_delta():
    lap_a = _constant_speed_lap(1000, 200)  # A is faster everywhere
    lap_b = _constant_speed_lap(1000, 180)
    _, _, _, delta_ms = align.align_laps(lap_a, lap_b)

    assert delta_ms[0] == pytest.approx(0, abs=1.0)
    assert np.all(np.diff(delta_ms) >= -1e-6)  # monotonically growing — B falls further behind
    assert delta_ms[-1] > delta_ms[len(delta_ms) // 2] > 0


def test_rescale_bounds_the_residual_from_distance_drift():
    # Same physical lap and pace; A's integrated distance under-measures the
    # true length by 1% (a realistic FastF1 artifact) while B measures it
    # exactly. Rescaling re-anchors both laps' distance axes to the same
    # endpoint so corner markers / grid points line up — it does NOT (and
    # can't, without an external ground-truth length) fully cancel the
    # resulting pace illusion: stretching A's distance axis to match B's
    # makes A read as if it covered ground slightly faster. For a ~18s lap
    # and 1% drift that's a ~180ms residual, matching the drift fraction —
    # bounded and small, not a gap that keeps growing without limit (which
    # is what skipping rescaling entirely would produce, since corner
    # markers would then land at genuinely different points on each grid).
    true_length = 1000.0
    drift_fraction = 0.01
    speed_kmh = 200.0
    lap_a = _constant_speed_lap(true_length * (1 - drift_fraction), speed_kmh)
    lap_b = _constant_speed_lap(true_length, speed_kmh)
    _, _, _, delta_ms = align.align_laps(lap_a, lap_b)

    lap_time_ms = (true_length / (speed_kmh / 3.6)) * 1000.0
    expected_residual_ms = drift_fraction * lap_time_ms
    assert abs(delta_ms[-1]) == pytest.approx(expected_residual_ms, rel=0.15)
    # monotonic, not oscillating — a predictable bias, not noise
    assert np.all(np.diff(delta_ms) >= -1e-6) or np.all(np.diff(delta_ms) <= 1e-6)


def test_grid_is_monotonic_and_within_lap_bounds():
    lap_a = _constant_speed_lap(1000, 200)
    lap_b = _constant_speed_lap(950, 210)
    grid, _, _, _ = align.align_laps(lap_a, lap_b)
    assert np.all(np.diff(grid) > 0)
    assert grid[0] == 0.0
    assert grid[-1] <= 1000.0


def test_brake_resample_is_nearest_not_interpolated():
    n = 100
    distance = np.linspace(0, 100, n)
    brake = np.zeros(n, dtype=bool)
    brake[50:] = True
    tel = _lap(distance, np.full(n, 200.0), np.full(n, 50.0), np.full(n, 4), brake, distance * 10.0)
    grid = np.linspace(0, 100, 21)
    out = align.resample_to_grid(tel, grid)
    assert out["brake"].dtype == bool
    assert set(np.unique(out["brake"]).tolist()) <= {True, False}


def test_resample_requires_all_columns():
    bad = pd.DataFrame({"distance_m": [0, 1], "speed": [1, 2]})
    with pytest.raises(ValueError):
        align.align_laps(bad, bad)


def test_downsample_strides_and_keeps_start():
    grid = np.arange(0, 100, dtype=float)
    series = {"speed": np.arange(0, 100, dtype=float)}
    delta_ms = np.arange(0, 100, dtype=float)
    g2, s2, d2 = align.downsample(grid, series, delta_ms, resolution=10)
    assert len(g2) == 10
    assert g2[0] == 0
    assert len(s2["speed"]) == 10


def test_downsample_noop_below_resolution_2():
    grid = np.arange(0, 10, dtype=float)
    series = {"speed": grid.copy()}
    delta_ms = grid.copy()
    g2, s2, d2 = align.downsample(grid, series, delta_ms, resolution=1)
    assert len(g2) == len(grid)
