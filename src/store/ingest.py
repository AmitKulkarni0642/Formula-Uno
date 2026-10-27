"""
Idempotent ingestion into the processed stats store.

    python -m src.store.ingest --season 2024 [--event 5] [--sessions Q,R]
                                [--telemetry fastest|none] [--force]

Backfills any season/event 2018-2026. Re-running without --force skips
sessions already logged as "ok" in ingest_log; a session that failed stays
"failed" and is retried automatically next run. One session's exception
never aborts the batch — it's logged and ingestion moves on.
"""

import argparse
import sys
import time
import traceback

import fastf1

from src.store import db, ids
from src.store.sources import fastf1_src

DEFAULT_SESSIONS = ["Q", "R"]


def ingest_session(con, season: int, round_number: int, code: str, telemetry: str, force: bool) -> str:
    evt_id = ids.event_id(season, round_number)
    sid = ids.session_id(evt_id, code)

    if not force and db.is_ingested(con, sid, "all"):
        return "skipped"

    try:
        frames = fastf1_src.load_session_frames(season, round_number, code, telemetry=telemetry)
    except Exception as e:
        db.log_ingest(con, sid, "all", "failed", 0, error=f"{type(e).__name__}: {e}")
        return f"failed: {e}"

    db.upsert_rows(con, "drivers", frames["drivers"], ["driver_id"])
    db.upsert_rows(con, "teams", frames["teams"], ["team_id"])
    db.replace_rows(con, "sessions", {"session_id": sid}, frames["sessions"])
    db.replace_rows(con, "entries", {"session_id": sid}, frames["entries"])
    db.replace_rows(con, "results", {"session_id": sid}, frames["results"])
    n_laps = db.replace_rows(con, "laps", {"session_id": sid}, frames["laps"])
    db.replace_rows(con, "minisectors", {"session_id": sid}, frames["minisectors"])

    db.delete_telemetry(evt_id, code)
    for did, tel_df in frames["telemetry_files"]:
        db.write_telemetry_parquet(sid, evt_id, code, did, tel_df)
    if frames["telemetry_files"]:
        db._refresh_telemetry_view(con)

    if not frames["track_outline"].empty:
        db.replace_rows(
            con, "track_outline",
            {"circuit_key": frames["circuit_key"], "season": frames["season"]},
            frames["track_outline"],
        )
    if not frames["corners"].empty:
        db.replace_rows(
            con, "corners",
            {"circuit_key": frames["circuit_key"], "season": frames["season"]},
            frames["corners"],
        )

    db.log_ingest(con, sid, "all", "ok", n_laps)
    return f"ok ({n_laps} laps, {len(frames['telemetry_files'])} telemetry traces)"


def ingest_season(con, season: int, rounds: list[int] | None, sessions: list[str], telemetry: str, force: bool):
    if rounds is None:
        sched = fastf1.get_event_schedule(season, include_testing=False)
        rounds = sorted(int(r) for r in sched["RoundNumber"] if r > 0)

    for round_number in rounds:
        try:
            evt_frame = fastf1_src.load_event_frame(season, round_number)
            db.upsert_rows(con, "events", evt_frame["row"], ["event_id"])
        except Exception as e:
            print(f"  {ids.event_id(season, round_number):<16} <event load failed>              "
                  f"failed: {type(e).__name__}: {e}")
            continue  # one bad event can't abort the rest of the season

        event_name = evt_frame["row"].iloc[0]["name"]

        for code in sessions:
            sid = ids.session_id(evt_frame["event_id"], code)
            t0 = time.time()
            try:
                status = ingest_session(con, season, round_number, code, telemetry, force)
            except Exception:
                status = "failed: " + traceback.format_exc(limit=1).strip().splitlines()[-1]
            print(f"  {sid:<16} {event_name:<30} {status}  ({time.time() - t0:.1f}s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--event", type=int, default=None, help="Round number; omit to ingest the whole season")
    ap.add_argument("--sessions", type=str, default=",".join(DEFAULT_SESSIONS), help="Comma-separated codes, e.g. Q,R,FP1")
    ap.add_argument("--telemetry", choices=["fastest", "none"], default="fastest")
    ap.add_argument("--force", action="store_true", help="Re-ingest even if already logged ok")
    args = ap.parse_args()

    sessions = [s.strip().upper() for s in args.sessions.split(",") if s.strip()]
    rounds = [args.event] if args.event else None

    con = db.connect()
    print(f"Ingesting season {args.season} "
          f"{'round ' + str(args.event) if args.event else '(full calendar)'} "
          f"sessions={sessions} telemetry={args.telemetry}{' [force]' if args.force else ''}")
    ingest_season(con, args.season, rounds, sessions, args.telemetry, args.force)
    con.close()


if __name__ == "__main__":
    sys.exit(main())
