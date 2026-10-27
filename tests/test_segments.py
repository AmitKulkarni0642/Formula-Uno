"""
Phase 2 segmentation correctness, per PLAN.md section 5's test list:
segment boundaries cover the lap with no gaps, and a shifted braking point
is recovered within one grid step.
"""

import numpy as np
import pytest

from src.compare import segments


def _corner(number: int, distance_m: float) -> dict:
    return {"number": number, "letter": "", "distance_m": distance_m, "x": 0.0, "y": 0.0, "angle": 0.0}


def test_segment_bounds_cover_whole_lap_with_no_gaps_or_overlaps():
    grid = np.arange(0, 1000, 1.0)
    corners = [_corner(1, 200), _corner(2, 500), _corner(3, 800)]
    bounds = segments.corner_segment_bounds(grid, corners)

    assert len(bounds) == 3
    assert bounds[0][0] == 0
    assert bounds[-1][1] == len(grid)  # last segment reaches the final sample, inclusive
    for (_, end_i, _), (start_j, _, _) in zip(bounds, bounds[1:]):
        assert end_i == start_j  # shared boundary — no gap, no double-counted metre


def _braking_zone_profile(grid, apex_idx, brake_on_idx, min_speed=80.0, max_speed=300.0):
    n = len(grid)
    into_corner = np.linspace(max_speed, min_speed, apex_idx + 1)
    out_of_corner = np.linspace(min_speed, max_speed, n - apex_idx - 1)
    speed = np.concatenate([into_corner, out_of_corner])[:n]
    brake = np.zeros(n, dtype=bool)
    brake[brake_on_idx:apex_idx + 1] = True
    throttle = np.where(np.arange(n) <= apex_idx, 0.0, 100.0)
    return speed, brake, throttle


def test_shifted_braking_point_recovered_within_one_grid_step():
    grid = np.arange(0, 300, 1.0)  # 1m grid -> "one grid step" = 1m
    apex_idx = 150

    speed_a, brake_a, throttle_a = _braking_zone_profile(grid, apex_idx, brake_on_idx=100)
    speed_b, brake_b, throttle_b = _braking_zone_profile(grid, apex_idx, brake_on_idx=120)  # brakes 20m later

    a = {"speed": speed_a, "brake": brake_a, "throttle": throttle_a}
    b = {"speed": speed_b, "brake": brake_b, "throttle": throttle_b}
    delta_ms = np.zeros(len(grid))
    corners = [_corner(1, float(grid[apex_idx]))]

    segs = segments.build_segments(grid, a, b, delta_ms, corners)
    assert len(segs) == 1
    assert segs[0]["braking_point_diff_m"] == pytest.approx(20.0, abs=1.0)
    assert segs[0]["category"] == "braking"


def test_apex_speed_diff_sign_and_magnitude():
    grid = np.arange(0, 300, 1.0)
    apex_idx = 150
    speed_a, brake_a, throttle_a = _braking_zone_profile(grid, apex_idx, brake_on_idx=100, min_speed=80.0)
    speed_b, brake_b, throttle_b = _braking_zone_profile(grid, apex_idx, brake_on_idx=100, min_speed=95.0)

    a = {"speed": speed_a, "brake": brake_a, "throttle": throttle_a}
    b = {"speed": speed_b, "brake": brake_b, "throttle": throttle_b}
    delta_ms = np.zeros(len(grid))
    corners = [_corner(1, float(grid[apex_idx]))]

    segs = segments.build_segments(grid, a, b, delta_ms, corners)
    assert segs[0]["min_speed_diff_kmh"] == pytest.approx(15.0, abs=0.5)  # B carries 15 km/h more


def test_time_delta_matches_delta_ms_at_segment_boundaries():
    grid = np.arange(0, 300, 1.0)
    apex_idx = 150
    speed_a, brake_a, throttle_a = _braking_zone_profile(grid, apex_idx, brake_on_idx=100)
    a = {"speed": speed_a, "brake": brake_a, "throttle": throttle_a}
    b = {k: v.copy() for k, v in a.items()}
    delta_ms = np.linspace(0, 500, len(grid))
    corners = [_corner(1, float(grid[apex_idx]))]

    segs = segments.build_segments(grid, a, b, delta_ms, corners)
    assert segs[0]["time_delta_s"] == pytest.approx((delta_ms[-1] - delta_ms[0]) / 1000.0, abs=1e-6)


def test_multi_corner_lap_produces_one_segment_per_corner():
    grid = np.arange(0, 1000, 1.0)
    n = len(grid)
    speed = np.full(n, 250.0)
    brake = np.zeros(n, dtype=bool)
    throttle = np.full(n, 100.0)
    a = {"speed": speed, "brake": brake, "throttle": throttle}
    b = {k: v.copy() for k, v in a.items()}
    delta_ms = np.zeros(n)
    corners = [_corner(i, d) for i, d in enumerate([150, 400, 700], start=1)]

    segs = segments.build_segments(grid, a, b, delta_ms, corners)
    assert len(segs) == 3
    assert [s["corner"] for s in segs] == [1, 2, 3]
