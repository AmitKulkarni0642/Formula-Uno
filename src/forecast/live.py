"""
Forecasting an event that HASN'T happened yet -- the "second set" the user
asked for, as opposed to features.py's backtesting path (train on seasons
that already happened, evaluate on a season that already happened).

The key difference: every historical "as of" row in pace.py/track_features.py
is computed as shift(1)-then-EWM, because the row's OWN event exists and must
be excluded from its own feature. A future event has no row at all yet, so
there's nothing to shift away -- the right "current form" value is the
EWM evaluated at the position immediately after the last REAL event, which
is mathematically what shift(1) would have produced for a hypothetical next
row. snapshot_pace()/snapshot_track() compute exactly that.
"""

import numpy as np
import pandas as pd

from src.ingestion.load_session import load_race
from src.store.ids import team_lineage_id
from src.forecast import schedule
from src.forecast.pace import build_pace_history
from src.forecast.track_features import build_track_history

HALFLIFE_EVENTS = 3.0


def current_roster(season: int, round_: int) -> pd.DataFrame:
    """
    Driver/team pairing as of right now: the most recently COMPLETED round
    before (season, round_) -- walks backward if the immediately preceding
    round is missing (cancelled, not yet ingested). A genuine squad change
    mid-weekend (reserve driver subbing in) isn't something this can see
    coming; it reflects the grid as it stood at the last race run.
    """
    events = schedule.all_events(season, season)
    events = events[(events["Season"] == season) & (events["Round"] < round_)].sort_values("Round", ascending=False)
    for _, ev in events.iterrows():
        try:
            results = load_race(season, int(ev["Round"]))["results"]
        except Exception:
            continue
        roster = results[["Abbreviation", "FullName", "TeamName"]].drop_duplicates(subset="Abbreviation").copy()
        roster["Team"] = roster["TeamName"].map(team_lineage_id)
        roster["AsOfRound"] = int(ev["Round"])
        return roster.reset_index(drop=True)
    raise ValueError(f"No completed round found before {season} round {round_} to read the roster from")


def _ewm_latest(series: pd.Series, halflife: float = HALFLIFE_EVENTS) -> float:
    """The 'one step past the last real row' EWM value -- see module docstring."""
    s = series.dropna()
    if s.empty:
        return float("nan")
    return float(s.ewm(halflife=halflife, min_periods=1).mean().iloc[-1])


def snapshot_pace(history_start_season: int, season: int, round_: int, session_type: str) -> dict:
    """Current team-pace / driver-vs-teammate form, as of right before (season, round_)."""
    events = schedule.all_events(history_start_season, season)
    events = schedule.events_before(events, season, round_)
    pace_hist = build_pace_history(events, session_type)

    team_pace: dict[str, float] = {}
    driver_vs_teammate: dict[str, float] = {}
    if not pace_hist.empty:
        team_rounds = (
            pace_hist.groupby(["Team", "Season", "Round", "EventDate"], as_index=False)["gap_to_fastest_s"]
            .mean().sort_values("EventDate")
        )
        for team, g in team_rounds.groupby("Team"):
            team_pace[team] = _ewm_latest(g["gap_to_fastest_s"])
        for driver, g in pace_hist.sort_values("EventDate").groupby("Driver"):
            driver_vs_teammate[driver] = _ewm_latest(g["teammate_gap_s"])
    return {"team_pace": team_pace, "driver_vs_teammate": driver_vs_teammate}


def snapshot_track(history_start_season: int, season: int, round_: int, session_type: str, circuit: str) -> dict:
    """Current circuit fingerprint for one circuit, as of right before (season, round_)."""
    events = schedule.all_events(history_start_season, season)
    events = schedule.events_before(events, season, round_)
    track_hist = build_track_history(events, session_type)
    track_hist = track_hist[track_hist["circuit"] == circuit].sort_values("EventDate")

    out: dict[str, float] = {}
    metric_cols = [c for c in track_hist.columns if c not in ("circuit", "Season", "Round", "EventDate")]
    for col in metric_cols:
        out[f"{col}_asof"] = _ewm_latest(track_hist[col]) if not track_hist.empty else float("nan")
    return out
