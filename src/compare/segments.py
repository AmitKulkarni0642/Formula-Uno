"""
Splits an aligned lap-pair into one segment per corner (braking -> apex ->
exit/traction, plus the straight before the next braking zone) and measures
how much time was gained/lost in each, with what dominated.

Braking-point detection is honestly approximate: at ~4 Hz telemetry and
300 km/h a sample spans ~20m, so "braked Xm later" has roughly that margin
of error. This is flagged in the API response, not hidden.
"""

import numpy as np

THROTTLE_PICKUP_PCT = 95.0  # throttle level that counts as "back to full exit throttle"


def _nearest_grid_index(grid: np.ndarray, distance: float) -> int:
    return int(np.clip(np.searchsorted(grid, distance), 0, len(grid) - 1))


def corner_segment_bounds(grid: np.ndarray, corners: list[dict]) -> list[tuple[int, int, dict]]:
    """
    One segment per corner, boundaries at the MIDPOINT between consecutive
    corner markers (not at the markers themselves) — that puts each corner's
    own apex inside its segment with room for both the braking/entry phase
    before it and the exit/traction phase after it. Using the raw corner
    distances as boundaries would clip one side or the other, and using
    "previous corner" for one edge and "next corner" for the other (an
    earlier version of this function did) makes adjacent segments overlap.

    Covers the whole lap with no gaps: boundary i is shared, byte-for-byte,
    by segment i's end and segment i+1's start.
    """
    sorted_corners = sorted(corners, key=lambda c: c["distance_m"])
    n = len(sorted_corners)
    marks = [c["distance_m"] for c in sorted_corners]

    boundaries = [0.0] + [(marks[i] + marks[i + 1]) / 2.0 for i in range(n - 1)] + [float(grid[-1])]

    bounds = []
    for i, c in enumerate(sorted_corners):
        start_idx = _nearest_grid_index(grid, boundaries[i])
        # last segment's end is len(grid), not nearest_grid_index(grid[-1]) (len(grid)-1)
        # — the latter would exclude the lap's final sample via Python's exclusive slicing.
        end_idx = _nearest_grid_index(grid, boundaries[i + 1]) if i + 1 < n else len(grid)
        if end_idx > start_idx:
            bounds.append((start_idx, end_idx, c))
    return bounds


def _first_brake_on(brake: np.ndarray, upto: int) -> int | None:
    window = brake[: upto + 1]
    if not window.any():
        return None
    return int(np.argmax(window))


def _first_throttle_pickup(throttle: np.ndarray, from_idx: int) -> int:
    window = throttle[from_idx:]
    hits = np.where(window >= THROTTLE_PICKUP_PCT)[0]
    return from_idx + int(hits[0]) if len(hits) else len(throttle) - 1


def build_segments(grid, a: dict, b: dict, delta_ms: np.ndarray, corners: list[dict]) -> list[dict]:
    segments = []
    for start_idx, end_idx, corner in corner_segment_bounds(grid, corners):
        sl = slice(start_idx, end_idx)
        speed_a, speed_b = a["speed"][sl], b["speed"][sl]
        throttle_a, throttle_b = a["throttle"][sl], b["throttle"][sl]
        brake_a, brake_b = a["brake"][sl], b["brake"][sl]

        apex_a = int(np.argmin(speed_a))
        apex_b = int(np.argmin(speed_b))

        brake_on_a = _first_brake_on(brake_a, apex_a)
        brake_on_b = _first_brake_on(brake_b, apex_b)
        braking_point_diff_m = (
            float(grid[sl][brake_on_b] - grid[sl][brake_on_a])
            if brake_on_a is not None and brake_on_b is not None else None
        )

        min_speed_diff_kmh = float(speed_b[apex_b] - speed_a[apex_a])

        exit_a = _first_throttle_pickup(throttle_a, apex_a)
        exit_b = _first_throttle_pickup(throttle_b, apex_b)
        throttle_pickup_diff_m = float(grid[sl][exit_b] - grid[sl][exit_a])
        exit_speed_diff_kmh = float(speed_b[exit_b] - speed_a[exit_a])
        top_speed_diff_kmh = float(np.max(speed_b) - np.max(speed_a))

        time_delta_s = float((delta_ms[sl][-1] - delta_ms[sl][0]) / 1000.0)

        magnitude = {
            "braking": abs(braking_point_diff_m) if braking_point_diff_m is not None else 0.0,
            "apex": abs(min_speed_diff_kmh),
            "traction": abs(exit_speed_diff_kmh),
            "straight-line": abs(top_speed_diff_kmh),
        }
        category = max(magnitude, key=magnitude.get) if any(magnitude.values()) else "straight-line"

        segments.append({
            "corner": corner["number"],
            "start_distance_m": float(grid[start_idx]),
            "end_distance_m": float(grid[end_idx - 1]),
            "time_delta_s": time_delta_s,
            "braking_point_diff_m": braking_point_diff_m,  # approximate — see module docstring
            "min_speed_diff_kmh": min_speed_diff_kmh,
            "throttle_pickup_diff_m": throttle_pickup_diff_m,
            "exit_speed_diff_kmh": exit_speed_diff_kmh,
            "top_speed_diff_kmh": top_speed_diff_kmh,
            "category": category,
        })
    return segments
