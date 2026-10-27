"""
Lap-by-lap race-pace comparison for two drivers over a WHOLE race: cumulative
gap evolution (who's ahead, by how much, and exactly when that flips), pit
stops, and each driver's tyre strategy — the "did the tyre offset work"
story (e.g. 2019 Hungary: Hamilton's extra stop let him close in and pass
Verstappen on fresher tyres). This is lap-level and race-long, not telemetry
— the 4Hz speed/throttle/brake traces from Phase 2's /compare_laps are
per-lap and don't stitch meaningfully across 70 laps of pit stops and
traffic. Gap evolution (cumulative lap time, like a broadcast "race trace"
chart) is what actually tells this story.
"""

import pandas as pd


def _driver_laps(con, session_id: str, driver_id: str) -> pd.DataFrame:
    return con.execute(
        "SELECT lap_number, lap_ms, compound, stint, pit_in, pit_out, track_status, position "
        "FROM laps WHERE session_id = ? AND driver_id = ? ORDER BY lap_number",
        [session_id, driver_id],
    ).fetchdf()


def _stints(laps: pd.DataFrame) -> list[dict]:
    stints = []
    for stint_no, grp in laps.dropna(subset=["stint"]).groupby("stint"):
        # Pace average excludes pit in/out laps — those are inflated by the
        # stop itself and would make the compound look slower than it raced.
        clean = grp[~grp["pit_in"].fillna(False) & ~grp["pit_out"].fillna(False) & grp["lap_ms"].notna()]
        compound = grp["compound"].dropna()
        stints.append({
            "stint": int(stint_no),
            "compound": compound.mode().iat[0] if len(compound) else None,
            "lap_start": int(grp["lap_number"].min()),
            "lap_end": int(grp["lap_number"].max()),
            "lap_count": int(len(grp)),
            "avg_lap_s": float(clean["lap_ms"].mean() / 1000.0) if len(clean) else None,
        })
    return stints


def _lead_changes(rows: list[dict]) -> list[dict]:
    """Laps where the sign of gap_s flips — the on-track order between these two actually changed."""
    changes = []
    prev_sign = None
    for r in rows:
        sign = (r["gap_s"] > 0) - (r["gap_s"] < 0)
        if sign != 0 and prev_sign is not None and sign != prev_sign:
            changes.append({"lap_number": r["lap_number"], "gap_s": r["gap_s"]})
        if sign != 0:
            prev_sign = sign
    return changes


def race_pace_comparison(con, session_id: str, driver_a: str, driver_b: str) -> dict:
    """
    gap_s[n] = (B's cumulative race time through lap n) - (A's cumulative
    race time through lap n) — positive means B is behind A, matching the
    b-minus-a convention used in Phase 2's align.py. This is exactly how a
    broadcast "race trace" / gap-to-leader chart is built: both drivers'
    own lap times (pit-stop time included, since it's real elapsed time)
    summed from lap 1, compared lap-for-lap. Valid for two drivers on the
    same lap count; stops at the first lap either driver is missing a time
    for (DNF, data gap) rather than inventing a "ghost" continuation.
    """
    laps_a = _driver_laps(con, session_id, driver_a)
    laps_b = _driver_laps(con, session_id, driver_b)
    if laps_a.empty or laps_b.empty:
        missing = driver_a if laps_a.empty else driver_b
        raise ValueError(f"No race laps for {missing!r} in {session_id!r}")

    common_laps = sorted(set(laps_a["lap_number"]) & set(laps_b["lap_number"]))
    a_by_lap = laps_a.set_index("lap_number")
    b_by_lap = laps_b.set_index("lap_number")

    cum_a_ms = cum_b_ms = 0.0
    rows = []
    for n in common_laps:
        ra, rb = a_by_lap.loc[n], b_by_lap.loc[n]
        if pd.isna(ra["lap_ms"]) or pd.isna(rb["lap_ms"]):
            break
        cum_a_ms += float(ra["lap_ms"])
        cum_b_ms += float(rb["lap_ms"])
        rows.append({
            "lap_number": int(n),
            "gap_s": (cum_b_ms - cum_a_ms) / 1000.0,
            "lap_time_a_s": float(ra["lap_ms"]) / 1000.0,
            "lap_time_b_s": float(rb["lap_ms"]) / 1000.0,
            "compound_a": ra["compound"], "compound_b": rb["compound"],
            "pit_lap_a": bool(ra["pit_in"]) if pd.notna(ra["pit_in"]) else False,
            "pit_lap_b": bool(rb["pit_in"]) if pd.notna(rb["pit_in"]) else False,
            "track_status": ra["track_status"],
        })

    return {
        "session_id": session_id,
        "driver_a": driver_a,
        "driver_b": driver_b,
        "laps_compared": len(rows),
        "laps_available": [int(n) for n in common_laps],
        "final_gap_s": rows[-1]["gap_s"] if rows else None,
        "lead_changes": _lead_changes(rows),
        "stints_a": _stints(laps_a),
        "stints_b": _stints(laps_b),
        "laps": rows,
    }
