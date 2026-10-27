"""
FastF1 source adapter: one session in -> the store's normalized frames out.

`sessions.source` (not yet populated — we only have one source) records which
adapter wrote each row, so a free-tier fallback (OpenF1 for 2023+, Jolpica for
results-only pre-2023) can be added later as a sibling module returning the
same shapes, without touching ingest.py or the schema.

Only FastF1 is implemented for now — D0 was decided in favour of an F1TV
subscription, which gives full telemetry coverage 2018-2026 through this one
source.
"""

import math
from datetime import datetime, timezone

import fastf1
import numpy as np
import pandas as pd

from src.ingestion.load_session import _attach_weather  # reuse the proven weather-join logic
from src.store import ids

N_MINISECTORS = 25


def _ms(td) -> int | None:
    """Timedelta -> whole milliseconds, or None (NaT)."""
    if td is None or pd.isna(td):
        return None
    return int(round(td.total_seconds() * 1000))


def _nullable_int(series: pd.Series) -> pd.Series:
    """
    Object-dtype column of python int/None. DuckDB's pandas registration
    (duckdb 2.0) doesn't understand pandas' nullable "Int64" extension dtype
    ("data type 'Int64' not understood"), so plain objects are used instead —
    DuckDB infers the real column type (INTEGER, with NULLs) from those fine.
    """
    s = pd.to_numeric(series, errors="coerce")
    return s.astype(object).where(s.notna(), None).map(lambda v: int(v) if v is not None else None)


def load_event_frame(season: int, round_number: int) -> dict:
    event = fastf1.get_event(season, round_number)
    evt_id = ids.event_id(season, round_number)
    return {
        "event_id": evt_id,
        "row": pd.DataFrame([{
            "event_id": evt_id,
            "season": season,
            "round": round_number,
            "name": event["EventName"],
            "circuit_key": ids.circuit_key(event["Location"]),
            "country": event["Country"],
            "date": pd.Timestamp(event["EventDate"]).date(),
            "era": ids.era_for_season(season),
            "format": event["EventFormat"],
        }]),
    }


def load_session_frames(season: int, round_number: int, code: str, telemetry: str = "fastest") -> dict:
    """
    telemetry: "fastest" (per-driver fastest lap -> telemetry+minisectors+track
    geometry) or "none" (timing/results only — faster, no car/position data).

    Returns a dict of DataFrames keyed by table name, plus "session_meta" and
    "telemetry_files" (list of (driver_id, df) to hand to db.write_telemetry_parquet).
    """
    evt_id = ids.event_id(season, round_number)
    sid = ids.session_id(evt_id, code)
    want_telemetry = telemetry != "none"

    session = fastf1.get_session(season, round_number, code)
    session.load(telemetry=want_telemetry, weather=True, messages=False, laps=True)

    results = session.results.copy()
    laps = _attach_weather(session, session.laps.copy())
    try:
        rainfall = session.laps.get_weather_data()["Rainfall"].astype(bool).to_numpy()
        if len(rainfall) == len(laps):
            laps["Rainfall"] = rainfall
        else:
            laps["Rainfall"] = False
    except Exception:
        laps["Rainfall"] = False

    drivers_df, teams_df, entries_df, results_df, driver_id_by_abbr = _people_and_results(sid, results)
    laps_df = _laps_frame(sid, laps, driver_id_by_abbr)

    minisectors_df = pd.DataFrame()
    telemetry_files: list[tuple[int, str, pd.DataFrame]] = []
    track_outline_df = pd.DataFrame()
    corners_df = pd.DataFrame()

    if want_telemetry:
        minisectors_df, telemetry_files = _fastest_lap_telemetry(session, sid, driver_id_by_abbr)
        track_outline_df, corners_df = _track_geometry(session, ids.circuit_key(session.event["Location"]), season)

    has_data = len(laps_df) > 0 or len(results_df) > 0
    sessions_df = pd.DataFrame([{
        "session_id": sid,
        "event_id": evt_id,
        "code": code,
        "start_utc": _session_start_utc(session),
        "has_telemetry": want_telemetry,
        "ingested_at": datetime.now(timezone.utc),
        "fastf1_version": fastf1.__version__,
        "status": "ok" if has_data else "no_data",
    }])

    return {
        "session_id": sid,
        "event_id": evt_id,
        "circuit_key": ids.circuit_key(session.event["Location"]),
        "season": season,
        "sessions": sessions_df,
        "drivers": drivers_df,
        "teams": teams_df,
        "entries": entries_df,
        "results": results_df,
        "laps": laps_df,
        "minisectors": minisectors_df,
        "telemetry_files": telemetry_files,
        "track_outline": track_outline_df,
        "corners": corners_df,
    }


def _session_start_utc(session):
    try:
        d = session.date
        if pd.isna(d):
            return None
        return pd.Timestamp(d).to_pydatetime()
    except Exception:
        return None


def _people_and_results(sid: str, results: pd.DataFrame):
    drivers_rows, teams_rows, entries_rows, results_rows = [], [], [], []
    driver_id_by_abbr: dict[str, str] = {}

    for _, r in results.iterrows():
        abbr = r.get("Abbreviation")
        full_name = r.get("FullName") or abbr
        if not abbr or pd.isna(full_name):
            continue
        did = ids.driver_id(full_name)
        driver_id_by_abbr[abbr] = did
        drivers_rows.append({"driver_id": did, "abbreviation": abbr, "full_name": full_name})

        team_name = r.get("TeamName")
        tid = ids.team_id(team_name) if pd.notna(team_name) else None
        if tid:
            teams_rows.append({
                "team_id": tid,
                "name": team_name,
                "color": f"#{r['TeamColor']}" if pd.notna(r.get("TeamColor")) and not str(r["TeamColor"]).startswith("#") else r.get("TeamColor"),
                "lineage_id": ids.team_lineage_id(team_name),
            })

        car_number = r.get("DriverNumber")
        entries_rows.append({
            "session_id": sid,
            "driver_id": did,
            "team_id": tid,
            "car_number": int(car_number) if pd.notna(car_number) else None,
        })

        has_quali_times = "Q1" in results.columns
        results_rows.append({
            "session_id": sid,
            "driver_id": did,
            "position": int(r["Position"]) if pd.notna(r.get("Position")) else None,
            "grid": int(r["GridPosition"]) if pd.notna(r.get("GridPosition")) else None,
            "status": r.get("Status") if pd.notna(r.get("Status")) else None,
            "points": float(r["Points"]) if pd.notna(r.get("Points")) else None,
            "q1_ms": _ms(r.get("Q1")) if has_quali_times else None,
            "q2_ms": _ms(r.get("Q2")) if has_quali_times else None,
            "q3_ms": _ms(r.get("Q3")) if has_quali_times else None,
        })

    drivers_df = pd.DataFrame(drivers_rows).drop_duplicates("driver_id") if drivers_rows else pd.DataFrame(
        columns=["driver_id", "abbreviation", "full_name"])
    teams_df = pd.DataFrame(teams_rows).drop_duplicates("team_id") if teams_rows else pd.DataFrame(
        columns=["team_id", "name", "color", "lineage_id"])
    entries_df = pd.DataFrame(entries_rows) if entries_rows else pd.DataFrame(
        columns=["session_id", "driver_id", "team_id", "car_number"])
    results_df = pd.DataFrame(results_rows) if results_rows else pd.DataFrame(
        columns=["session_id", "driver_id", "position", "grid", "status", "points", "q1_ms", "q2_ms", "q3_ms"])

    if not entries_df.empty:
        entries_df["car_number"] = _nullable_int(entries_df["car_number"])
    for col in ("position", "grid", "q1_ms", "q2_ms", "q3_ms"):
        if not results_df.empty:
            results_df[col] = _nullable_int(results_df[col])

    return drivers_df, teams_df, entries_df, results_df, driver_id_by_abbr


def _laps_frame(sid: str, laps: pd.DataFrame, driver_id_by_abbr: dict[str, str]) -> pd.DataFrame:
    if laps is None or laps.empty:
        return pd.DataFrame()

    rows = []
    for _, lap in laps.iterrows():
        abbr = lap.get("Driver")
        did = driver_id_by_abbr.get(abbr)
        if did is None:
            continue  # driver not in session results (rare — reserve/practice-only entries)
        rows.append({
            "session_id": sid,
            "driver_id": did,
            "lap_number": int(lap["LapNumber"]) if pd.notna(lap.get("LapNumber")) else None,
            "lap_ms": _ms(lap.get("LapTime")),
            "s1_ms": _ms(lap.get("Sector1Time")),
            "s2_ms": _ms(lap.get("Sector2Time")),
            "s3_ms": _ms(lap.get("Sector3Time")),
            "compound": lap.get("Compound") if pd.notna(lap.get("Compound")) else None,
            "stint": int(lap["Stint"]) if pd.notna(lap.get("Stint")) else None,
            "tyre_life": int(lap["TyreLife"]) if pd.notna(lap.get("TyreLife")) else None,
            "fresh_tyre": bool(lap["FreshTyre"]) if pd.notna(lap.get("FreshTyre")) else None,
            "pit_in": pd.notna(lap.get("PitInTime")),
            "pit_out": pd.notna(lap.get("PitOutTime")),
            "track_status": str(lap["TrackStatus"]) if pd.notna(lap.get("TrackStatus")) else None,
            "is_deleted": bool(lap["Deleted"]) if pd.notna(lap.get("Deleted")) else False,
            "deleted_reason": lap.get("DeletedReason") if pd.notna(lap.get("DeletedReason")) else None,
            "is_accurate": bool(lap["IsAccurate"]) if pd.notna(lap.get("IsAccurate")) else None,
            "position": int(lap["Position"]) if pd.notna(lap.get("Position")) else None,
            "session_time_ms": _ms(lap.get("Time")),
            "air_temp": float(lap["AirTemp"]) if pd.notna(lap.get("AirTemp")) else None,
            "track_temp": float(lap["TrackTemp"]) if pd.notna(lap.get("TrackTemp")) else None,
            "rainfall": bool(lap["Rainfall"]) if pd.notna(lap.get("Rainfall")) else False,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("lap_ms", "s1_ms", "s2_ms", "s3_ms", "tyre_life", "position", "session_time_ms", "stint"):
        df[col] = _nullable_int(df[col])
    # a session can legitimately replay a lap number once per stint restart (rare); keep first
    df = df.drop_duplicates(["session_id", "driver_id", "lap_number"], keep="first")
    return df


def _fastest_lap_telemetry(session, sid: str, driver_id_by_abbr: dict[str, str]):
    minisector_rows = []
    telemetry_files: list[tuple[int, str, pd.DataFrame]] = []

    for abbr, did in driver_id_by_abbr.items():
        try:
            driver_laps = session.laps.pick_drivers(abbr)
            lap = driver_laps.pick_fastest()
            if lap is None or pd.isna(lap.get("LapTime")):
                continue
            tel = lap.get_telemetry()
            if tel is None or tel.empty or "Distance" not in tel.columns:
                continue
        except Exception:
            continue

        tel = tel.sort_values("Distance").reset_index(drop=True)
        lap_number = int(lap["LapNumber"]) if pd.notna(lap.get("LapNumber")) else None

        t_ms = tel["Time"].apply(lambda td: _ms(td) or 0).to_numpy()
        drs_raw = pd.to_numeric(tel.get("DRS", pd.Series(0, index=tel.index)), errors="coerce").fillna(0)

        tel_df = pd.DataFrame({
            "lap_number": lap_number,
            "sample_idx": np.arange(len(tel)),
            "t_ms": t_ms,
            "distance_m": tel["Distance"].to_numpy(dtype=float),
            "speed": pd.to_numeric(tel.get("Speed"), errors="coerce").to_numpy(dtype=float),
            "throttle": pd.to_numeric(tel.get("Throttle"), errors="coerce").to_numpy(dtype=float),
            "brake": tel.get("Brake", False).astype(bool).to_numpy(),
            "gear": _nullable_int(tel.get("nGear", pd.Series(dtype=float))).to_numpy(),
            "rpm": pd.to_numeric(tel.get("RPM"), errors="coerce").to_numpy(dtype=float),
            "drs": (drs_raw >= 10).to_numpy(),  # FastF1 convention: 10/12/14 = DRS open
            "x": pd.to_numeric(tel.get("X"), errors="coerce").to_numpy(dtype=float),
            "y": pd.to_numeric(tel.get("Y"), errors="coerce").to_numpy(dtype=float),
        })
        telemetry_files.append((did, tel_df))

        minisector_rows.extend(_minisector_times(sid, did, lap_number, tel))

    minisectors_df = pd.DataFrame(minisector_rows) if minisector_rows else pd.DataFrame()
    return minisectors_df, telemetry_files


def _minisector_times(sid: str, did: str, lap_number: int | None, tel: pd.DataFrame) -> list[dict]:
    """
    Cumulative elapsed time at 26 equal-distance checkpoints (0..lap length),
    by linear interpolation -> 25 per-segment durations. Approximate at ~4Hz
    sampling, same honesty caveat as the corner-segmentation in Phase 2.
    """
    dist = tel["Distance"].to_numpy(dtype=float)
    t = tel["Time"].apply(lambda td: td.total_seconds() if pd.notna(td) else np.nan).to_numpy()
    valid = ~np.isnan(dist) & ~np.isnan(t)
    dist, t = dist[valid], t[valid]
    if len(dist) < 2 or lap_number is None:
        return []

    order = np.argsort(dist)
    dist, t = dist[order], t[order]
    dist, uniq_idx = np.unique(dist, return_index=True)
    t = t[uniq_idx]
    if len(dist) < 2:
        return []

    checkpoints = np.linspace(dist[0], dist[-1], N_MINISECTORS + 1)
    t_at_checkpoint = np.interp(checkpoints, dist, t)

    rows = []
    for i in range(N_MINISECTORS):
        delta_s = t_at_checkpoint[i + 1] - t_at_checkpoint[i]
        rows.append({
            "session_id": sid,
            "driver_id": did,
            "lap_number": lap_number,
            "ms_index": i,
            "time_ms": int(round(delta_s * 1000)) if math.isfinite(delta_s) else None,
        })
    return rows


def _track_geometry(session, circuit_key_val: str, season: int):
    try:
        lap = session.laps.pick_fastest()
        tel = lap.get_telemetry()
        if tel is None or tel.empty:
            return pd.DataFrame(), pd.DataFrame()
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    tel = tel.reset_index(drop=True)
    outline_df = pd.DataFrame({
        "circuit_key": circuit_key_val,
        "season": season,
        "idx": np.arange(len(tel)),
        "x": pd.to_numeric(tel.get("X"), errors="coerce"),
        "y": pd.to_numeric(tel.get("Y"), errors="coerce"),
        "distance_m": pd.to_numeric(tel.get("Distance"), errors="coerce"),
    })

    corners_rows = []
    try:
        for _, c in session.get_circuit_info().corners.iterrows():
            letter = c.get("Letter")
            corners_rows.append({
                "circuit_key": circuit_key_val,
                "season": season,
                "number": int(c["Number"]),
                "letter": letter.strip() if isinstance(letter, str) and letter.strip() else "",
                "distance_m": float(c["Distance"]) if pd.notna(c.get("Distance")) else None,
                "x": float(c["X"]),
                "y": float(c["Y"]),
                "angle": float(c["Angle"]) if pd.notna(c.get("Angle")) else None,
            })
    except Exception:
        pass
    corners_df = pd.DataFrame(corners_rows)
    return outline_df, corners_df
