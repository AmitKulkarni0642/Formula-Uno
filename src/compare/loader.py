"""
Resolves "driver + lap_spec" to actual telemetry for /compare_laps.

Phase 1 ingestion only stores each driver's fastest lap per session (storing
every lap would be tens of GB for little benefit). Anything else — a
teammate's lap 12, a specific out-lap — is fetched live from FastF1 on
demand and written back into the same Parquet partition as a lazy cache, so
asking for it twice only pays the FastF1 round trip once.
"""

import pandas as pd

from src.store import db
from src.store.sources import fastf1_src


class LapNotFound(ValueError):
    pass


def _resolve_lap_number(con, session_id: str, driver_id: str, lap_spec: str) -> int:
    if lap_spec == "fastest":
        row = con.execute(
            "SELECT lap_number FROM laps WHERE session_id = ? AND driver_id = ? AND lap_ms IS NOT NULL "
            "ORDER BY lap_ms ASC LIMIT 1",
            [session_id, driver_id],
        ).fetchall()
        if not row:
            raise LapNotFound(f"No valid lap for {driver_id} in {session_id}")
        return int(row[0][0])
    try:
        return int(lap_spec)
    except (TypeError, ValueError):
        raise LapNotFound(f"lap must be 'fastest' or a lap number, got {lap_spec!r}")


def _driver_abbreviation(con, driver_id: str) -> str:
    row = con.execute("SELECT abbreviation FROM drivers WHERE driver_id = ?", [driver_id]).fetchall()
    if not row:
        raise LapNotFound(f"Unknown driver_id {driver_id!r}")
    return row[0][0]


def get_lap_telemetry(con, session_id: str, driver_id: str, lap_spec: str) -> tuple[pd.DataFrame, int]:
    """Returns (telemetry_df, lap_number). Raises LapNotFound if the driver/lap doesn't exist."""
    lap_number = _resolve_lap_number(con, session_id, driver_id, lap_spec)

    cached = con.execute(
        "SELECT COUNT(*) FROM telemetry WHERE session_id = ? AND driver_id = ? AND lap_number = ?",
        [session_id, driver_id, lap_number],
    ).fetchall()[0][0]

    if cached:
        df = con.execute(
            "SELECT * FROM telemetry WHERE session_id = ? AND driver_id = ? AND lap_number = ? ORDER BY sample_idx",
            [session_id, driver_id, lap_number],
        ).fetchdf()
        return df, lap_number

    season_str, round_str, code = session_id.split("-")
    abbr = _driver_abbreviation(con, driver_id)
    df = fastf1_src.load_specific_lap_telemetry(int(season_str), int(round_str), code, abbr, lap_number)

    event_id = f"{season_str}-{round_str}"
    db.write_telemetry_parquet(session_id, event_id, code, driver_id, df, file_stem=f"{driver_id}__lap{lap_number}")
    db._refresh_telemetry_view(con)
    return df, lap_number


def get_corners(con, session_id: str) -> list[dict]:
    row = con.execute(
        "SELECT e.circuit_key, e.season FROM sessions s JOIN events e USING(event_id) WHERE s.session_id = ?",
        [session_id],
    ).fetchall()
    if not row:
        raise LapNotFound(f"Unknown session_id {session_id!r}")
    circuit_key, season = row[0]

    corners = con.execute(
        "SELECT number, letter, distance_m, x, y, angle FROM corners "
        "WHERE circuit_key = ? AND season = ? ORDER BY number",
        [circuit_key, season],
    ).fetchdf()
    return corners.to_dict("records")
