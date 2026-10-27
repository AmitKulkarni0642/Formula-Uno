"""
The store's whole safety story is "DELETE-then-INSERT per session, inside a
transaction" (replace_rows) for session-scoped tables, and "INSERT ... ON
CONFLICT DO UPDATE" (upsert_rows) for global tables (drivers/teams/events)
that get written again every time a session featuring them is ingested.
These tests exercise both against an in-memory DuckDB — no network, no real
store — so a backfill can be re-run (or retried after a crash) without ever
duplicating rows.
"""

import duckdb
import pandas as pd
import pytest

from src.store import db


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute(db._SCHEMA_SQL)
    yield c
    c.close()


def _laps_df(session_id: str, driver_id: str, n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "session_id": [session_id] * n,
        "driver_id": [driver_id] * n,
        "lap_number": list(range(1, n + 1)),
        "lap_ms": [90000 + i for i in range(n)],
        "s1_ms": [None] * n, "s2_ms": [None] * n, "s3_ms": [None] * n,
        "compound": ["SOFT"] * n, "stint": [1] * n, "tyre_life": [1] * n,
        "fresh_tyre": [True] * n, "pit_in": [False] * n, "pit_out": [False] * n,
        "track_status": ["1"] * n, "is_deleted": [False] * n, "deleted_reason": [None] * n,
        "is_accurate": [True] * n, "position": [1] * n, "session_time_ms": [0] * n,
        "air_temp": [25.0] * n, "track_temp": [35.0] * n, "rainfall": [False] * n,
    })


def test_replace_rows_rerun_does_not_duplicate(con):
    df = _laps_df("2024-01-R", "max_verstappen", 3)
    db.replace_rows(con, "laps", {"session_id": "2024-01-R"}, df)
    db.replace_rows(con, "laps", {"session_id": "2024-01-R"}, df)  # re-ingest the same session
    n = con.execute("SELECT COUNT(*) FROM laps WHERE session_id = '2024-01-R'").fetchone()[0]
    assert n == 3


def test_replace_rows_shrinks_when_new_data_has_fewer_rows(con):
    db.replace_rows(con, "laps", {"session_id": "2024-01-R"}, _laps_df("2024-01-R", "max_verstappen", 5))
    db.replace_rows(con, "laps", {"session_id": "2024-01-R"}, _laps_df("2024-01-R", "max_verstappen", 2))
    n = con.execute("SELECT COUNT(*) FROM laps WHERE session_id = '2024-01-R'").fetchone()[0]
    assert n == 2  # stale rows from the larger first write are gone, not accumulated


def test_replace_rows_only_touches_its_own_session(con):
    db.replace_rows(con, "laps", {"session_id": "2024-01-R"}, _laps_df("2024-01-R", "max_verstappen", 3))
    db.replace_rows(con, "laps", {"session_id": "2024-02-R"}, _laps_df("2024-02-R", "max_verstappen", 4))
    db.replace_rows(con, "laps", {"session_id": "2024-01-R"}, _laps_df("2024-01-R", "max_verstappen", 1))
    assert con.execute("SELECT COUNT(*) FROM laps WHERE session_id = '2024-01-R'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM laps WHERE session_id = '2024-02-R'").fetchone()[0] == 4


def test_upsert_rows_merges_global_table_without_duplicating(con):
    row1 = pd.DataFrame([{"driver_id": "max_verstappen", "abbreviation": "VER", "full_name": "Max Verstappen"}])
    row2 = pd.DataFrame([{"driver_id": "max_verstappen", "abbreviation": "VER", "full_name": "Max Verstappen"}])
    db.upsert_rows(con, "drivers", row1, ["driver_id"])
    db.upsert_rows(con, "drivers", row2, ["driver_id"])  # same driver written again (different session)
    assert con.execute("SELECT COUNT(*) FROM drivers").fetchone()[0] == 1


def test_upsert_rows_keeps_rows_for_other_keys(con):
    db.upsert_rows(con, "drivers", pd.DataFrame([{"driver_id": "a", "abbreviation": "AAA", "full_name": "A"}]), ["driver_id"])
    db.upsert_rows(con, "drivers", pd.DataFrame([{"driver_id": "b", "abbreviation": "BBB", "full_name": "B"}]), ["driver_id"])
    assert con.execute("SELECT COUNT(*) FROM drivers").fetchone()[0] == 2


def test_ingest_log_roundtrip(con):
    assert db.is_ingested(con, "2024-01-R", "all") is False
    db.log_ingest(con, "2024-01-R", "all", "ok", rows=1125)
    assert db.is_ingested(con, "2024-01-R", "all") is True

    db.log_ingest(con, "2024-02-R", "all", "failed", rows=0, error="boom")
    assert db.is_ingested(con, "2024-02-R", "all") is False  # failed != ok, so it's retried next run


def test_log_ingest_rerun_replaces_not_duplicates(con):
    db.log_ingest(con, "2024-01-R", "all", "failed", rows=0, error="boom")
    db.log_ingest(con, "2024-01-R", "all", "ok", rows=1125)
    rows = con.execute("SELECT status FROM ingest_log WHERE session_id = '2024-01-R' AND step = 'all'").fetchall()
    assert rows == [("ok",)]
