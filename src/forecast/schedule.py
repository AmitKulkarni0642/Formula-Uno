"""
Global event calendar, 2018-2026, used to walk "every event in order" when
building rolling pace history or running a walk-forward backtest.

Kept separate from src/store (which has its own `events` table) because the
store's backfill is partial and Phase 4 training must not block on it —
this reads the schedule straight from FastF1, same as the rest of the old
prediction engine's data path.
"""

import fastf1
import pandas as pd

FIRST_SEASON = 2018


def season_events(year: int) -> pd.DataFrame:
    """
    Real points-paying rounds for one season, in calendar order.

    Drops testing (RoundNumber == 0) and any row without a date, which is
    FastF1's own signal for a round that hasn't happened yet (e.g. asking
    for 2026 after only 7 rounds have run).
    """
    sched = fastf1.get_event_schedule(year, include_testing=False)
    sched = sched[sched["RoundNumber"] > 0].copy()
    sched = sched[sched["EventDate"].notna()]
    sched["Season"] = year
    return sched[["Season", "RoundNumber", "EventName", "EventDate", "Location", "Country"]].rename(
        columns={"RoundNumber": "Round"}
    ).sort_values(["Season", "Round"]).reset_index(drop=True)


def all_events(start_year: int = FIRST_SEASON, end_year: int | None = None) -> pd.DataFrame:
    """
    Every real round across start_year..end_year (inclusive), in chronological
    order. end_year defaults to the current year's schedule (whatever FastF1
    currently knows about — future rounds in the current season are excluded
    by season_events's EventDate filter, but FastF1 sometimes publishes a
    full-season calendar with provisional dates before the season starts;
    callers that need "only events that have actually happened" should also
    filter on EventDate <= today).
    """
    end_year = end_year or pd.Timestamp.now().year
    frames = [season_events(yr) for yr in range(start_year, end_year + 1)]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["Season", "Round", "EventName", "EventDate", "Location", "Country"]
    )


def events_before(events: pd.DataFrame, season: int, round_: int) -> pd.DataFrame:
    """
    Strict chronological prefix: every event before (season, round_), used to
    enforce the leakage rule (a forecast for event E may only look at events
    that finished before E).
    """
    key = season * 100 + round_
    ek = events["Season"] * 100 + events["Round"]
    return events[ek < key].copy()
