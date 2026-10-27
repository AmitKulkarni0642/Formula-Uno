"""
DuckDB connection + idempotent writes for the processed stats store.

Every relational write is DELETE-then-INSERT for one session (or one
circuit+season for track_outline/corners), inside a transaction, so
re-ingesting a session already stored — or recovering from a half-written
one — never leaves duplicates. See PLAN.md section 4 for the full design.
"""

from pathlib import Path

import duckdb
import pandas as pd

from src.settings import settings

STORE_DIR = Path(settings.store_dir)
DB_PATH = STORE_DIR / "f1.duckdb"
TELEMETRY_DIR = STORE_DIR / "telemetry"

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


def connect() -> duckdb.DuckDBPyConnection:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(_SCHEMA_SQL)
    _refresh_telemetry_view(con)
    return con


def _refresh_telemetry_view(con: duckdb.DuckDBPyConnection) -> None:
    """
    (Re)create the `telemetry` view over the Parquet partitions. DuckDB needs
    at least one real file to infer the glob's schema, so this is a no-op
    (not an error) until the first telemetry write exists.
    """
    glob = str(TELEMETRY_DIR / "*" / "*" / "*" / "*.parquet").replace("\\", "/")
    try:
        con.execute(
            f"CREATE OR REPLACE VIEW telemetry AS "
            f"SELECT * FROM read_parquet('{glob}', hive_partitioning = true)"
        )
    except duckdb.Error:
        pass  # no telemetry written yet


def replace_rows(con: duckdb.DuckDBPyConnection, table: str, key: dict, df: pd.DataFrame | None) -> int:
    """
    DELETE WHERE <key columns match> then INSERT df, in one transaction.
    `key` maps column -> value, e.g. {"session_id": sid} or
    {"circuit_key": ck, "season": yr}.
    """
    where = " AND ".join(f"{col} = ?" for col in key)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM {table} WHERE {where}", list(key.values()))
        n = 0
        if df is not None and not df.empty:
            con.register("_tmp_df", df)
            cols = ", ".join(df.columns)
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _tmp_df")
            con.unregister("_tmp_df")
            n = len(df)
        con.execute("COMMIT")
        return n
    except Exception:
        con.execute("ROLLBACK")
        raise


def upsert_rows(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame | None, key_cols: list[str]) -> int:
    """
    INSERT ... ON CONFLICT DO UPDATE for tables NOT scoped to one session
    (drivers, teams, events) — a driver/team/event is written again every time
    a session that features them is ingested, so this has to merge, not
    delete-then-insert (which would wipe everything from one call, every call).
    """
    if df is None or df.empty:
        return 0
    con.register("_tmp_df", df)
    cols = ", ".join(df.columns)
    keys = ", ".join(key_cols)
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in df.columns if c not in key_cols)
    sql = f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _tmp_df ON CONFLICT ({keys})"
    sql += f" DO UPDATE SET {set_clause}" if set_clause else " DO NOTHING"
    con.execute(sql)
    con.unregister("_tmp_df")
    return len(df)


def write_telemetry_parquet(session_id: str, event_id: str, code: str, driver_id: str, df: pd.DataFrame) -> Path:
    """
    One Parquet file per driver, hive-partitioned by event_id/code so a
    session's files can be deleted+rewritten as a unit (see delete_telemetry).
    """
    season, round_part = event_id.split("-")
    part_dir = TELEMETRY_DIR / f"season={season}" / f"event={round_part}" / f"session={code}"
    part_dir.mkdir(parents=True, exist_ok=True)
    path = part_dir / f"{driver_id}.parquet"
    df.assign(session_id=session_id, driver_id=driver_id).to_parquet(path, index=False)
    return path


def delete_telemetry(event_id: str, code: str) -> None:
    season, round_part = event_id.split("-")
    part_dir = TELEMETRY_DIR / f"season={season}" / f"event={round_part}" / f"session={code}"
    if part_dir.exists():
        for f in part_dir.glob("*.parquet"):
            f.unlink()


def log_ingest(con: duckdb.DuckDBPyConnection, session_id: str, step: str, status: str, rows: int, error: str | None = None) -> None:
    con.execute("DELETE FROM ingest_log WHERE session_id = ? AND step = ?", [session_id, step])
    con.execute(
        "INSERT INTO ingest_log (session_id, step, status, rows, finished_at, error) "
        "VALUES (?, ?, ?, ?, now(), ?)",
        [session_id, step, status, rows, error],
    )


def is_ingested(con: duckdb.DuckDBPyConnection, session_id: str, step: str) -> bool:
    row = con.execute(
        "SELECT status FROM ingest_log WHERE session_id = ? AND step = ?", [session_id, step]
    ).fetchone()
    return row is not None and row[0] == "ok"
