"""
Orchestrates one /compare_laps request: load both laps' telemetry + this
session's corners from the store, align them, segment by corner, rank
insights — the full Phase 2 pipeline behind one endpoint.
"""

from src.compare import align, insights, loader, segments

CAVEATS = (
    "Telemetry samples at roughly 4Hz, so point-in-time metrics (braking point, "
    "apex) carry an inherent margin of error of a few metres. Distance axes are "
    "rescaled to a shared reference length to keep corner markers aligned across "
    "both laps; this does not fully cancel a pace illusion when the two laps' "
    "raw distance measurements drifted by different amounts (see src/compare/align.py)."
)


def compare_laps(con, session_id: str, driver_a: str, lap_a: str, driver_b: str, lap_b: str, resolution: int = 1) -> dict:
    tel_a, lap_no_a = loader.get_lap_telemetry(con, session_id, driver_a, lap_a)
    tel_b, lap_no_b = loader.get_lap_telemetry(con, session_id, driver_b, lap_b)
    corners = loader.get_corners(con, session_id)

    grid, a, b, delta_ms = align.align_laps(tel_a, tel_b)
    seg = segments.build_segments(grid, a, b, delta_ms, corners)
    ranked = insights.rank_insights(seg, driver_a, driver_b)

    display_grid, display_a, display_delta = align.downsample(grid, a, delta_ms, resolution)
    _, display_b, _ = align.downsample(grid, b, delta_ms, resolution)

    return {
        "meta": {
            "session_id": session_id,
            "driver_a": driver_a, "lap_a": lap_no_a,
            "driver_b": driver_b, "lap_b": lap_no_b,
            "sample_rate_hz_approx": 4,
            "caveats": CAVEATS,
        },
        "distance_m": display_grid.tolist(),
        "speed_a": display_a["speed"].tolist(), "speed_b": display_b["speed"].tolist(),
        "throttle_a": display_a["throttle"].tolist(), "throttle_b": display_b["throttle"].tolist(),
        "brake_a": [bool(v) for v in display_a["brake"]], "brake_b": [bool(v) for v in display_b["brake"]],
        "gear_a": display_a["gear"].tolist(), "gear_b": display_b["gear"].tolist(),
        "delta_ms": display_delta.tolist(),
        "total_delta_s": float(delta_ms[-1] / 1000.0) if len(delta_ms) else 0.0,
        "segments": seg,
        "insights": ranked,
        "minisector_winners": _minisector_winners(con, session_id, driver_a, lap_no_a, driver_b, lap_no_b),
    }


def _minisector_winners(con, session_id: str, driver_a: str, lap_a: int, driver_b: str, lap_b: int) -> list[str | None]:
    """
    Backs the "track map coloured by faster driver per mini-sector" visual.
    Only populated when BOTH laps are ones Phase 1 bulk-ingested (minisectors
    are computed for each driver's fastest lap only, not for an on-demand
    single-lap fetch) — otherwise this is an empty/partial list, not an error.
    """
    rows = con.execute(
        "SELECT driver_id, ms_index, time_ms FROM minisectors "
        "WHERE session_id = ? AND ((driver_id = ? AND lap_number = ?) OR (driver_id = ? AND lap_number = ?)) "
        "ORDER BY ms_index",
        [session_id, driver_a, lap_a, driver_b, lap_b],
    ).fetchall()

    by_ms: dict[int, dict[str, int]] = {}
    for driver_id, ms_index, time_ms in rows:
        by_ms.setdefault(ms_index, {})[driver_id] = time_ms

    winners: list[str | None] = []
    for ms_index in sorted(by_ms):
        times = by_ms[ms_index]
        if driver_a in times and driver_b in times:
            winners.append(driver_a if times[driver_a] <= times[driver_b] else driver_b)
        else:
            winners.append(None)
    return winners
