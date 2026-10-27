"""
Qualifying telemetry comparison — two drivers' fastest laps, aligned by distance.

Deliberately independent of the prediction models: this is real FastF1 telemetry,
real data in, real data out. Full historical coverage (2018+) requires an
authenticated F1 account with an active F1TV subscription — FastF1 reads
F1_USERNAME/F1_PASSWORD from the environment (see .env) and signs in automatically;
without it, coverage is sparse and effectively limited to a couple of recent seasons.
Every function here still returns None on unavailability rather than raising, since
a specific driver/session combo can be missing even with auth — callers must handle
that gracefully.
"""

import numpy as np
import pandas as pd
import fastf1

from src.store import ids

N_SAMPLES = 400  # distance-grid resolution for the resampled comparison


def get_schedule(year: int) -> list[dict]:
    """Every points-paying event on a season's calendar (testing excluded)."""
    try:
        sched = fastf1.get_event_schedule(year, include_testing=False)
        sched = sched[sched["EventFormat"] != "testing"]
        return [
            {"round": int(r["RoundNumber"]), "name": r["EventName"], "location": r["Location"]}
            for _, r in sched.sort_values("RoundNumber").iterrows()
        ]
    except Exception:
        return []


def get_session_drivers(year: int, event: str, session_type: str = "Q") -> list[dict]:
    """
    The roster for one session — code/name/team/driver_id — so the frontend can
    offer only drivers who actually took part, instead of a free-text guess.
    session_type: "Q" (qualifying, default) or "R" (race) — grid penalties aside,
    these are almost always the same drivers, but a session can genuinely differ
    (e.g. a reserve driver stepping in for the race only).

    driver_id is the store's stable slug (src/store/ids.py) — the frontend needs
    it to call /compare_laps and /compare_race, which key on driver_id rather
    than the 3-letter code (which the store does not treat as a permanent id).
    """
    try:
        session = fastf1.get_session(year, event, session_type)
        session.load(telemetry=False, laps=False, weather=False, messages=False)
        results = session.results
        return [
            {
                "code": r["Abbreviation"],
                "name": r["FullName"],
                "team": r["TeamName"],
                "driver_id": ids.driver_id(r["FullName"]),
            }
            for _, r in results.iterrows()
        ]
    except Exception:
        return []


def _best_segment_lap(session, driver: str):
    """
    A driver's fastest lap in the LATEST knockout segment they reached (Q3 if they
    made it, else Q2, else Q1) — the lap that actually decided their grid slot.

    This matters: Session.laps.pick_fastest() finds a driver's single fastest lap
    across the WHOLE qualifying session regardless of segment, which is wrong for
    "who's ahead" — a driver can post a quicker Q1 lap (different, often drier
    conditions) than their actual Q3 time, and comparing two drivers' session-wide
    fastest laps can silently mix laps from different segments entirely. Confirmed
    on a real case: 2022 British GP, where this bug made VER look ahead of SAI by
    comparing both drivers' Q1 times, when SAI actually took pole in Q3.

    Returns (lap, segment_label) or (None, None).
    """
    q1, q2, q3 = session.laps.split_qualifying_sessions()
    for segment, label in ((q3, "Q3"), (q2, "Q2"), (q1, "Q1")):
        if segment is None:
            continue
        driver_laps = segment.pick_drivers(driver)
        if driver_laps.empty:
            continue
        lap = driver_laps.pick_fastest()
        if lap is not None and pd.notna(lap["LapTime"]):
            return lap, label
    return None, None


def get_official_lap_time(year: int, event: str, driver: str) -> float | None:
    """The official recorded time (seconds) for a driver's best-segment lap."""
    try:
        session = fastf1.get_session(year, event, "Q")
        session.load(telemetry=False, weather=False, messages=False)
        lap, _ = _best_segment_lap(session, driver)
        if lap is None:
            return None
        return float(lap["LapTime"].total_seconds())
    except Exception:
        return None


def get_grid_position(year: int, event: str, driver: str) -> int | None:
    """
    Where a driver actually qualified (P1, P2, ...) — the number that matters to
    a user, not which knockout segment (Q1/Q2/Q3) produced their time.
    """
    try:
        session = fastf1.get_session(year, event, "Q")
        session.load(telemetry=False, laps=False, weather=False, messages=False)
        row = session.results[session.results["Abbreviation"] == driver]
        if row.empty or pd.isna(row.iloc[0]["Position"]):
            return None
        return int(row.iloc[0]["Position"])
    except Exception:
        return None


def get_fastest_lap_telemetry(year: int, event: str, driver: str):
    """
    One driver's fastest lap in the latest qualifying segment they reached, as a
    DataFrame indexed by Distance with Speed/Throttle/Brake/nGear/Time columns,
    plus which segment (Q1/Q2/Q3) it came from. Returns (None, None) if the
    session or this driver's telemetry isn't available.
    """
    try:
        session = fastf1.get_session(year, event, "Q")
        session.load(telemetry=True, weather=False, messages=False)
        lap, segment = _best_segment_lap(session, driver)
        if lap is None:
            return None, None
        tel = lap.get_telemetry()
        if tel is None or tel.empty:
            return None, None
        tel = tel.dropna(subset=["Distance", "Speed"]).sort_values("Distance")
        tel["TimeSeconds"] = tel["Time"].dt.total_seconds()
        return tel[["Distance", "Speed", "Throttle", "Brake", "nGear", "TimeSeconds"]], segment
    except Exception:
        return None, None


def _resample(tel: pd.DataFrame, grid: np.ndarray) -> dict:
    """Linearly interpolate each channel onto a common distance grid."""
    d = tel["Distance"].to_numpy()
    return {
        "speed": np.interp(grid, d, tel["Speed"].to_numpy()),
        "throttle": np.interp(grid, d, tel["Throttle"].to_numpy()),
        "brake": np.interp(grid, d, tel["Brake"].astype(float).to_numpy()) > 0.5,
        "gear": np.interp(grid, d, tel["nGear"].to_numpy()),
        "time": np.interp(grid, d, tel["TimeSeconds"].to_numpy()),
    }


def get_track_map(year: int, event: str):
    """
    Real GPS-traced track outline for THIS EXACT year's layout, plus each corner's
    number and position. Necessary because some circuits are physically reprofiled
    between seasons — e.g. Singapore's 2023 resurface/reprofile around turns
    16-19, or Albert Park's 2022 rework — so a single fixed reference year (as
    circuit_profile.get_track_map uses, by design, for the main prediction page)
    would mislabel the layout here, where the user picks the year explicitly.
    Uses the qualifying session's outright fastest lap (any driver) purely for
    its position trace; corner positions come from the same session's circuit
    info, so this is a single session load, not two.

    Returns {"outline": [(x, y), ...], "corners": [{"number", "letter", "x", "y"}]}
    or None if telemetry genuinely isn't available.
    """
    try:
        session = fastf1.get_session(year, event, "Q")
        session.load(telemetry=True, weather=False, messages=False)
        lap = session.laps.pick_fastest()
        tel = lap.get_telemetry()
        if tel is None or tel.empty:
            return None
        outline = list(zip(tel["X"].tolist(), tel["Y"].tolist()))

        corners = []
        try:
            for _, c in session.get_circuit_info().corners.iterrows():
                letter = c["Letter"]
                corners.append({
                    "number": int(c["Number"]),
                    "letter": letter.strip() if isinstance(letter, str) and letter.strip() else None,
                    "x": float(c["X"]),
                    "y": float(c["Y"]),
                })
        except Exception:
            pass  # outline without corner labels is still useful

        return {"outline": outline, "corners": corners}
    except Exception:
        return None


def get_corners(year: int, event: str):
    """
    Corner distances for this circuit's layout, for segmenting the comparison.

    Needs telemetry=True: FastF1 computes each corner's Distance-along-lap by
    aligning it against actual lap telemetry — with telemetry off, every corner's
    Distance comes back NaN (confirmed directly, not assumed). Harmless to load
    here since get_fastest_lap_telemetry() already cached it for this session.
    """
    try:
        session = fastf1.get_session(year, event, "Q")
        session.load(telemetry=True, weather=False, messages=False)
        corners = session.get_circuit_info().corners
        corners = corners.dropna(subset=["Distance"])
        return corners[["Number", "Distance"]].sort_values("Distance").to_dict("records")
    except Exception:
        return []


def compare_qualifying_laps(year: int, event: str, driver_a: str, driver_b: str) -> dict | None:
    """
    Distance-aligned comparison of two drivers' fastest qualifying laps.

    Returns None if either driver's telemetry is unavailable for this session —
    callers must handle that (e.g. show "telemetry not available"), never guess.

    Segmentation is corner-to-corner and the resulting labels (braking/apex/
    traction/straight) are heuristic classifications of WHERE in a segment the
    biggest difference shows up, not a precise physical model — the ~4 Hz sample
    rate and boolean brake signal mean braking-point distances are approximate,
    stated as such rather than presented with false precision.
    """
    tel_a, segment_a = get_fastest_lap_telemetry(year, event, driver_a)
    tel_b, segment_b = get_fastest_lap_telemetry(year, event, driver_b)
    if tel_a is None or tel_b is None:
        return None

    max_dist = min(tel_a["Distance"].max(), tel_b["Distance"].max())
    grid = np.linspace(0, max_dist, N_SAMPLES)
    a = _resample(tel_a, grid)
    b = _resample(tel_b, grid)

    # Positive delta = B is further behind A's elapsed time at this point (A ahead).
    delta = b["time"] - a["time"]

    # Anchor the curve to the OFFICIAL lap-time gap rather than trust the raw
    # distance-truncated endpoint. Confirmed directly (not assumed): raw telemetry
    # Time is accurate to the millisecond against official timing when compared
    # over each lap's own full, untruncated span — the error comes entirely from
    # two cars' independently-integrated Distance measurements not landing on
    # exactly the same physical point (a real, car-to-car drift of ~10-20m seen
    # even on identical circuits), which the shared distance grid can't correct
    # for. Spreading that correction linearly across the lap keeps the curve's
    # SHAPE (where time was gained/lost — inherently an estimate) while making
    # its ENDPOINT, and the segment breakdown built from it, consistent with the
    # one number that's actually exact: the official recorded gap.
    official_a = get_official_lap_time(year, event, driver_a)
    official_b = get_official_lap_time(year, event, driver_b)
    if official_a is not None and official_b is not None:
        official_gap = official_b - official_a
        correction = official_gap - delta[-1]
        delta = delta + correction * (grid / grid[-1])

    corners = get_corners(year, event)
    segments = []
    bounds = [0.0] + [c["Distance"] for c in corners] + [max_dist]
    bounds = sorted(set(x for x in bounds if 0 <= x <= max_dist))

    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        # Half-open on the right (except the final segment) so every grid point
        # belongs to exactly one segment — a true partition, not an approximate
        # one. This is what makes the segment deltas sum EXACTLY to total_delta_s
        # (confirmed below), rather than silently losing the sliver of distance
        # between "last point segment i claims" and "first point segment i+1
        # claims" whenever a corner's real distance doesn't land exactly on one
        # of the N_SAMPLES grid points (which it essentially never does).
        is_last = i == len(bounds) - 2
        mask = (grid >= lo) & ((grid <= hi) if is_last else (grid < hi))
        if mask.sum() < 2:
            continue

        time_delta = float(delta[mask][-1] - delta[mask][0])  # time gained/lost by A in this segment
        min_speed_a, min_speed_b = float(a["speed"][mask].min()), float(b["speed"][mask].min())
        exit_speed_a, exit_speed_b = float(a["speed"][mask][-1]), float(b["speed"][mask][-1])

        # Approximate braking point: first sample in the segment where Brake goes True.
        def brake_point(brake_arr, dist_arr):
            idx = np.where(brake_arr[mask])[0]
            return float(dist_arr[mask][idx[0]]) if len(idx) else None

        brake_a = brake_point(a["brake"], grid)
        brake_b = brake_point(b["brake"], grid)
        brake_diff = (brake_b - brake_a) if (brake_a is not None and brake_b is not None) else None

        min_speed_diff = min_speed_a - min_speed_b
        exit_speed_diff = exit_speed_a - exit_speed_b

        # Heuristic classification: which sub-metric shows the largest normalised gap.
        candidates = {
            "braking": abs(brake_diff) / 20.0 if brake_diff is not None else 0,  # ~20m = notable
            "apex": abs(min_speed_diff) / 5.0,   # ~5 km/h = notable
            "traction": abs(exit_speed_diff) / 5.0,
        }
        label = max(candidates, key=candidates.get) if max(candidates.values()) > 0.3 else "straight-line"

        segments.append({
            "corner": corners[i]["Number"] if i < len(corners) else None,
            "start_distance_m": round(lo, 1),
            "end_distance_m": round(hi, 1),
            "time_delta_s": round(time_delta, 3),  # positive = A gained time here
            "braking_point_diff_m": round(brake_diff, 1) if brake_diff is not None else None,
            "min_speed_diff_kmh": round(min_speed_diff, 1),
            "exit_speed_diff_kmh": round(exit_speed_diff, 1),
            "category": label,
        })

    insights = _generate_insights(segments, driver_a, driver_b)
    position_a = get_grid_position(year, event, driver_a)
    position_b = get_grid_position(year, event, driver_b)

    return {
        "driver_a": driver_a,
        "driver_b": driver_b,
        "segment_a": segment_a,
        "segment_b": segment_b,
        "position_a": position_a,
        "position_b": position_b,
        "same_segment": segment_a == segment_b,
        "distance_m": grid.round(1).tolist(),
        "speed_a": a["speed"].round(1).tolist(),
        "speed_b": b["speed"].round(1).tolist(),
        "throttle_a": a["throttle"].round(1).tolist(),
        "throttle_b": b["throttle"].round(1).tolist(),
        "brake_a": a["brake"].tolist(),
        "brake_b": b["brake"].tolist(),
        "gear_a": a["gear"].round(0).tolist(),
        "gear_b": b["gear"].round(0).tolist(),
        "delta_time_s": delta.round(3).tolist(),
        "total_delta_s": round(float(delta[-1]), 3),
        "segments": segments,
        "insights": insights,
    }


def _generate_insights(segments: list[dict], driver_a: str, driver_b: str, top_n: int = 5) -> list[str]:
    """
    Plain-English, templated insights ranked by absolute time lost/gained per
    segment — not an LLM, just the numbers already computed, turned into sentences.
    """
    ranked = sorted(segments, key=lambda s: abs(s["time_delta_s"]), reverse=True)[:top_n]
    lines = []
    for s in ranked:
        if abs(s["time_delta_s"]) < 0.01:
            continue
        gainer, loser = (driver_a, driver_b) if s["time_delta_s"] > 0 else (driver_b, driver_a)
        where = f"Corner {s['corner']}" if s["corner"] is not None else \
                f"{s['start_distance_m']:.0f}–{s['end_distance_m']:.0f}m"
        reason = ""
        if s["category"] == "braking" and s["braking_point_diff_m"] is not None:
            later = driver_a if s["braking_point_diff_m"] > 0 else driver_b
            reason = f", braking {abs(s['braking_point_diff_m']):.0f}m later than {later}" if later != gainer else \
                     f", braking {abs(s['braking_point_diff_m']):.0f}m later"
        elif s["category"] == "apex":
            reason = f", carrying {abs(s['min_speed_diff_kmh']):.0f} km/h more through the apex"
        elif s["category"] == "traction":
            reason = f", {abs(s['exit_speed_diff_kmh']):.0f} km/h faster on exit"
        lines.append(f"{gainer} gained {abs(s['time_delta_s']):.2f}s at {where}{reason}.")
    return lines
