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


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    read_only=True lets the API serve from the store while a separate
    ingestion process holds the write connection — DuckDB allows one writer
    plus any number of read-only readers on the same file concurrently.
    The API should always connect read_only; only ingest.py writes.
    """
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        con.execute(_SCHEMA_SQL)
        _refresh_telemetry_view(con)  # a view's query (incl. its glob) re-evaluates on
        # every read, so a read-only connection sees new Parquet files automatically
        # once the view exists — it never needs to (and, being read-only, can't) redefine it.
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


def write_telemetry_parquet(
    session_id: str, event_id: str, code: str, driver_id: str, df: pd.DataFrame, file_stem: str | None = None,
) -> Path:
    """
    One Parquet file per driver (per lap, for a non-fastest lap fetched
    on demand — see src/compare/loader.py), hive-partitioned by
    event_id/code so a session's files can be deleted+rewritten as a unit
    (see delete_telemetry).

    `file_stem` only disambiguates the FILENAME when more than one lap for
    the same driver is cached in one session (the bulk fastest-lap write
    doesn't need it — one file per driver is already unique there). It must
    never be used in place of `driver_id` for the content itself, or every
    query that filters WHERE driver_id = ? silently stops matching that lap.
    """
    season, round_part = event_id.split("-")
    part_dir = TELEMETRY_DIR / f"season={season}" / f"event={round_part}" / f"session={code}"
    part_dir.mkdir(parents=True, exist_ok=True)
    path = part_dir / f"{file_stem or driver_id}.parquet"
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
    # fetchall(), not fetchone(): a result that isn't fully drained leaves the
    # connection in a state where the NEXT execute()/register() call raises
    # "Resource In Use Error: connection has an unfinished result" — hit this
    # for real on the first backfill run (crashed on every season's 2nd event).
    rows = con.execute(
        "SELECT status FROM ingest_log WHERE session_id = ? AND step = ?", [session_id, step]
    ).fetchall()
    return bool(rows) and rows[0][0] == "ok"
