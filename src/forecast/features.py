"""
Global feature frame: assembles pace.py's rolling team/driver form and
track_features.py's circuit fingerprint into one lap-level table a model can
train on across any circuit and era, race or qualifying.

Fixes a real bug in the old per-circuit pipeline (src/features/build_features.py
+ src/analytics/qualifying.py): the old qualifying "prediction" used the
driver's REAL RACE GRID POSITION as a feature -- which the real grid position
*is* (barring penalties), so it was feeding qualifying's own answer back in as
an input. Here, qualifying has no grid-position feature at all; the rolling
pace features (built only from events strictly before this one) stand in for
"how fast is this car/driver right now" instead.

Deliberately excludes Driver/Team/Circuit identity entirely -- that's the
point of the restructuring: a model trained on these features can be asked
about a team, driver or circuit it never saw in training, as long as it has a
little recent history (or, for a circuit, at least one of its "its own past"
is empty and the caller falls back to the field median, same philosophy as
build_features.py's clip_temp()).
"""

import numpy as np
import pandas as pd

from src.ingestion.load_session import load_race, load_qualifying
from src.store.ids import team_lineage_id, circuit_key as _circuit_key, era_for_season
from src.analytics.qualifying import extract_best_qualifying_laps
from src.forecast import schedule
from src.forecast.pace import clean_laps, build_pace_history, rolling_pace_asof
from src.forecast.track_features import build_track_history, rolling_track_asof

COMPOUND_ORDER = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTERMEDIATE": 3, "WET": 4}
ERA_ORDER = {"2018-21": 0, "2022-25": 1, "2026+": 2}
FIRST_SEASON = schedule.FIRST_SEASON
START_FUEL_KG = 105.0
QUAL_FUEL_KG = 5.0

# Continuous features, standardized before the network; categorical features
# go through an nn.Embedding instead of one-hot/label encoding.
CONTINUOUS_COLS = [
    "team_pace_asof_s", "driver_vs_teammate_asof_s",
    "typical_laptime_s_asof", "power_sensitivity_kmh_asof",
    "degradation_s_per_lap_asof", "position_change_rate_asof",
    "TyreLife", "TyreLifeSquared", "FuelLoad", "TrackTemp", "AirTemp",
    "LapNumber", "YearsSinceStart",
]
RACE_ONLY_CONTINUOUS = ["GridPosition"]
CATEGORICAL_COLS = ["CompoundEncoded", "EraEncoded"]
TARGET_COL = "LapTimeSeconds"


def _asof_tables(events: pd.DataFrame, session_type: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    pace = rolling_pace_asof(build_pace_history(events, session_type))
    track = rolling_track_asof(build_track_history(events, session_type))
    return pace, track


def _attach_pace(laps: pd.DataFrame, pace_asof_event: pd.DataFrame) -> pd.DataFrame:
    cols = pace_asof_event[["Driver", "team_pace_asof_s", "driver_vs_teammate_asof_s"]]
    return laps.merge(cols, on="Driver", how="left")


def _attach_track(laps: pd.DataFrame, track_asof_event: pd.DataFrame) -> pd.DataFrame:
    fp_cols = [c for c in track_asof_event.columns if c.endswith("_asof")]
    for col in fp_cols:
        laps[col] = track_asof_event[col].iloc[0] if len(track_asof_event) else float("nan")
    # degradation/position-change-rate only exist for the race-sourced fingerprint;
    # a qualifying-only sweep's track history won't have them, so backfill as NaN.
    for col in ("power_sensitivity_kmh_asof", "degradation_s_per_lap_asof", "position_change_rate_asof"):
        if col not in laps.columns:
            laps[col] = float("nan")
    return laps


def build_event_frame(season: int, round_: int, session_type: str,
                       pace_asof: pd.DataFrame, track_asof: pd.DataFrame) -> pd.DataFrame:
    """
    One event's lap-level rows, features attached. `pace_asof`/`track_asof`
    must already be the full as-of tables from _asof_tables() over the whole
    sweep this event belongs to -- NOT recomputed per event, since the rolling
    value for event N depends on seeing (and excluding) events < N.
    """
    if session_type == "R":
        data = load_race(season, round_)
        raw_laps = data["laps"]
        total_laps = int(raw_laps["LapNumber"].max())
        laps = clean_laps(raw_laps).copy()
        laps["LapTimeSeconds"] = laps["s"]
        laps["FuelLoad"] = START_FUEL_KG - (laps["LapNumber"] - 1) * (START_FUEL_KG / total_laps)
        grid = data["results"][["Abbreviation", "GridPosition"]].rename(columns={"Abbreviation": "Driver"})
        grid["GridPosition"] = pd.to_numeric(grid["GridPosition"], errors="coerce")
        laps = laps.merge(grid, on="Driver", how="left")
    else:
        data = load_qualifying(season, round_)
        laps = extract_best_qualifying_laps(data["laps"]).copy()
        laps["FuelLoad"] = QUAL_FUEL_KG
        # No GridPosition feature here -- deliberately. See module docstring.

    if laps.empty:
        return laps

    laps["Team"] = laps["Team"].map(team_lineage_id)
    laps["TyreLifeSquared"] = laps["TyreLife"] ** 2
    laps["CompoundEncoded"] = laps["Compound"].map(COMPOUND_ORDER).fillna(1).astype(int)
    laps["EraEncoded"] = ERA_ORDER[era_for_season(season)]
    laps["YearsSinceStart"] = float(season - FIRST_SEASON)
    laps["Season"] = season
    laps["Round"] = round_

    event_key = (pace_asof["Season"] == season) & (pace_asof["Round"] == round_)
    laps = _attach_pace(laps, pace_asof[event_key])
    track_key = (track_asof["Season"] == season) & (track_asof["Round"] == round_)
    laps = _attach_track(laps, track_asof[track_key])

    keep = ["Driver", "Team", "Compound", "Season", "Round", TARGET_COL] + CONTINUOUS_COLS + CATEGORICAL_COLS
    if session_type == "R":
        keep += RACE_ONLY_CONTINUOUS
    return laps[[c for c in keep if c in laps.columns]].copy()


def build_training_frame(seasons: list[int], session_type: str, history_start_season: int = FIRST_SEASON) -> pd.DataFrame:
    """
    Every clean lap (race) or best lap (qualifying) across `seasons`, with
    leakage-safe rolling features attached. The as-of tables are built over
    EVERY event from `history_start_season` up to and including the latest
    season requested (not just the requested seasons) so that, e.g.,
    training on [2022, 2023, 2024] still gives 2022's early rounds a
    cold-start rather than artificially rich history, while an evaluation
    sweep over [2025] correctly sees all of 2022-2024 as its "prior" history.

    `history_start_season` defaults to the project's full 2018 range, but
    callers whose seasons start at a regulation reset (2022's clean-sheet
    rules make 2018-21 pace data nearly uninformative for 2022 competitiveness)
    can raise it to skip loading seasons whose rolling contribution would be
    negligible anyway -- a real time cost, since each season is dozens of
    FastF1 session loads.
    """
    all_events = schedule.all_events(history_start_season, max(seasons))
    pace_asof, track_asof = _asof_tables(all_events, session_type)

    target_events = all_events[all_events["Season"].isin(seasons)]
    frames = []
    for _, ev in target_events.iterrows():
        try:
            frame = build_event_frame(int(ev["Season"]), int(ev["Round"]), session_type, pace_asof, track_asof)
        except Exception:
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["Driver", "Team", TARGET_COL] + CONTINUOUS_COLS + CATEGORICAL_COLS)
    return pd.concat(frames, ignore_index=True)
