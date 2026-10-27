-- Processed stats store (Phase 1). Relational tables live in one DuckDB file;
-- per-sample telemetry lives in Parquet partitions under STORE_DIR/telemetry/
-- and is exposed as the `telemetry` view below (created by db.py once at least
-- one file exists, since DuckDB needs a real file to infer a glob's schema).
--
-- Every write is DELETE-then-INSERT for one session (or one circuit+season for
-- track_outline/corners), inside a transaction — see src/store/db.py. Re-running
-- ingestion for a session already stored never leaves duplicates.

CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR PRIMARY KEY,
    season INTEGER,
    round INTEGER,
    name VARCHAR,
    circuit_key VARCHAR,
    country VARCHAR,
    date DATE,
    era VARCHAR,
    format VARCHAR
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR PRIMARY KEY,
    event_id VARCHAR,
    code VARCHAR,
    start_utc TIMESTAMP,
    has_telemetry BOOLEAN,
    ingested_at TIMESTAMP,
    fastf1_version VARCHAR,
    status VARCHAR
);

CREATE TABLE IF NOT EXISTS drivers (
    driver_id VARCHAR PRIMARY KEY,
    abbreviation VARCHAR,
    full_name VARCHAR
);

CREATE TABLE IF NOT EXISTS teams (
    team_id VARCHAR PRIMARY KEY,
    name VARCHAR,
    color VARCHAR,
    lineage_id VARCHAR
);

CREATE TABLE IF NOT EXISTS entries (
    session_id VARCHAR,
    driver_id VARCHAR,
    team_id VARCHAR,
    car_number INTEGER,
    PRIMARY KEY (session_id, driver_id)
);

CREATE TABLE IF NOT EXISTS results (
    session_id VARCHAR,
    driver_id VARCHAR,
    position INTEGER,
    grid INTEGER,
    status VARCHAR,
    points DOUBLE,
    q1_ms INTEGER,
    q2_ms INTEGER,
    q3_ms INTEGER,
    PRIMARY KEY (session_id, driver_id)
);

CREATE TABLE IF NOT EXISTS laps (
    session_id VARCHAR,
    driver_id VARCHAR,
    lap_number INTEGER,
    lap_ms INTEGER,
    s1_ms INTEGER,
    s2_ms INTEGER,
    s3_ms INTEGER,
    compound VARCHAR,
    stint INTEGER,
    tyre_life INTEGER,
    fresh_tyre BOOLEAN,
    pit_in BOOLEAN,
    pit_out BOOLEAN,
    track_status VARCHAR,
    is_deleted BOOLEAN,
    deleted_reason VARCHAR,
    is_accurate BOOLEAN,
    position INTEGER,
    session_time_ms BIGINT,
    air_temp DOUBLE,
    track_temp DOUBLE,
    rainfall BOOLEAN,
    PRIMARY KEY (session_id, driver_id, lap_number)
);

-- Fastest lap only, split into 25 equal-distance segments — cheap enough to
-- keep as a table; backs the "track map coloured by faster driver per
-- mini-sector" signature visual without touching full telemetry.
CREATE TABLE IF NOT EXISTS minisectors (
    session_id VARCHAR,
    driver_id VARCHAR,
    lap_number INTEGER,
    ms_index INTEGER,
    time_ms INTEGER,
    PRIMARY KEY (session_id, driver_id, lap_number, ms_index)
);

-- One reference lap's GPS trace per circuit+season (tracks get reprofiled,
-- e.g. Singapore 2023) — not per-session, since the layout doesn't change
-- within a season.
CREATE TABLE IF NOT EXISTS track_outline (
    circuit_key VARCHAR,
    season INTEGER,
    idx INTEGER,
    x DOUBLE,
    y DOUBLE,
    distance_m DOUBLE,
    PRIMARY KEY (circuit_key, season, idx)
);

CREATE TABLE IF NOT EXISTS corners (
    circuit_key VARCHAR,
    season INTEGER,
    number INTEGER,
    letter VARCHAR,
    distance_m DOUBLE,
    x DOUBLE,
    y DOUBLE,
    angle DOUBLE,
    PRIMARY KEY (circuit_key, season, number, letter)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    session_id VARCHAR,
    step VARCHAR,
    status VARCHAR,
    rows INTEGER,
    finished_at TIMESTAMP,
    error VARCHAR,
    PRIMARY KEY (session_id, step)
);
