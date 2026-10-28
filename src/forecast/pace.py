"""
Rolling competitive-pace features — the piece that lets ONE model generalise
across every circuit and every season, replacing the old per-circuit engine's
LabelEncoded Driver/Team/Track identities (which only mean anything for the
10 circuits and 3 seasons they were fit on).

Idea: instead of naming a car/driver, describe how far off the fastest car
they have been running lately (seconds, clean laps, normalised per-session so
Monaco's ~70s laps and Spa's ~104s laps are comparable). That number means
the same thing in any season, on any circuit, including ones the model never
trained on.

Leakage rule (the whole point of "forecast" vs "reconstruction"): a feature
"as of" event E must be built only from events strictly BEFORE E. Every
rolling function here shifts by one event per group before averaging, so the
event being forecast never leaks into its own feature.
"""

import pandas as pd

from src.ingestion.load_session import load_race, load_qualifying
from src.store.ids import team_lineage_id

WET_COMPOUNDS = ("INTERMEDIATE", "WET")


def _clean_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Same honesty filter as the old build_features: dry, accurate, timed laps."""
    laps = laps.copy()
    laps["s"] = laps["LapTime"].dt.total_seconds()
    mask = (
        laps["s"].notna()
        & laps["IsAccurate"]
        & ~laps["Deleted"].fillna(False).astype(bool)
        & laps["Compound"].notna()
        & ~laps["Compound"].isin(WET_COMPOUNDS)
    )
    if "TrackStatus" in laps.columns:
        ts = laps["TrackStatus"].astype(str)
        mask &= ~(ts.str.contains("4") | ts.str.contains("6"))
    return laps[mask]


def session_pace(year: int, event, session_type: str) -> pd.DataFrame:
    """
    One session's competitive picture: each driver's median clean lap, gap to
    the session's fastest, team identity (lineage-mapped), and gap to their
    own teammate(s) in that same session.

    Returns columns: Driver, Team, driver_median_s, gap_to_fastest_s,
    teammate_gap_s. Raises/propagates whatever FastF1 raises for an
    unavailable session (cancelled, wet-only, not yet run) — callers in a
    historical sweep catch and skip.
    """
    loader = load_race if session_type == "R" else load_qualifying
    data = loader(year, event)
    laps = _clean_laps(data["laps"])
    if laps.empty:
        return pd.DataFrame(columns=["Driver", "Team", "driver_median_s", "gap_to_fastest_s", "teammate_gap_s"])

    per_driver = laps.groupby("Driver").agg(driver_median_s=("s", "median"), Team=("Team", "first"))
    per_driver["Team"] = per_driver["Team"].map(team_lineage_id)
    fastest = per_driver["driver_median_s"].min()
    per_driver["gap_to_fastest_s"] = per_driver["driver_median_s"] - fastest

    team_mean = per_driver.groupby("Team")["driver_median_s"].transform("mean")
    team_n = per_driver.groupby("Team")["driver_median_s"].transform("size")
    # teammate_gap_s = driver's own time minus the OTHER drivers' mean on the same
    # team; for a 1-car-sampled team (team_n == 1, e.g. a mid-season substitution
    # with no team-mate lap this session) there is nothing to compare to.
    other_mean = (team_mean * team_n - per_driver["driver_median_s"]) / (team_n - 1)
    per_driver["teammate_gap_s"] = (per_driver["driver_median_s"] - other_mean).where(team_n > 1)

    return per_driver.reset_index()[["Driver", "Team", "driver_median_s", "gap_to_fastest_s", "teammate_gap_s"]]


def build_pace_history(events: pd.DataFrame, session_type: str) -> pd.DataFrame:
    """
    Walk `events` (from schedule.all_events, already in chronological order)
    and stack session_pace() for every one into a long history table:
    Season, Round, EventDate, Driver, Team, gap_to_fastest_s, teammate_gap_s.

    Events with no usable session (cancelled, not yet run, or a FastF1 fetch
    error) are silently skipped — this is a historical sweep over whatever
    actually happened, not a data-completeness check.
    """
    rows = []
    for _, ev in events.iterrows():
        try:
            pace = session_pace(int(ev["Season"]), int(ev["Round"]), session_type)
        except Exception:
            continue
        if pace.empty:
            continue
        pace["Season"] = int(ev["Season"])
        pace["Round"] = int(ev["Round"])
        pace["EventDate"] = ev["EventDate"]
        rows.append(pace)
    if not rows:
        return pd.DataFrame(columns=["Season", "Round", "EventDate", "Driver", "Team",
                                      "gap_to_fastest_s", "teammate_gap_s"])
    return pd.concat(rows, ignore_index=True).sort_values(["EventDate", "Season", "Round"]).reset_index(drop=True)


def rolling_pace_asof(history: pd.DataFrame, halflife_events: float = 3.0) -> pd.DataFrame:
    """
    Add 'as of this event' rolling features to a pace-history table: each
    team's/driver's recent form BEFORE the event in that row, via an
    exponentially-weighted mean over a group's own past values (shift(1)
    first, so the event's own result never contributes to its own feature).

    Adds: team_pace_asof_s (rolling mean of gap_to_fastest_s per Team),
          driver_vs_teammate_asof_s (rolling mean of teammate_gap_s per Driver).
    NaN on a group's first-ever appearance (no prior history) — callers fill
    with a neutral value (e.g. the grid median) rather than zero, which would
    falsely claim "exactly as fast as the fastest car".

    team_pace_asof_s is computed on TEAM-ROUND aggregates, not raw driver
    rows: a team fields two (or more) drivers per round, each with their own
    row, so rolling directly over driver-rows would make each row's lag-1
    neighbour its TEAMMATE's same-round result half the time, rather than
    the team's own prior round — both drivers on a team must see the exact
    same "as of this event" team number.
    """
    history = history.sort_values(["EventDate", "Season", "Round"]).copy()

    team_rounds = (
        history.groupby(["Team", "Season", "Round", "EventDate"], as_index=False)["gap_to_fastest_s"]
        .mean()
        .sort_values(["EventDate", "Season", "Round"])
    )
    team_rounds["team_pace_asof_s"] = (
        team_rounds.groupby("Team")["gap_to_fastest_s"]
        .transform(lambda s: s.shift(1).ewm(halflife=halflife_events, min_periods=1).mean())
    )
    history = history.merge(
        team_rounds[["Team", "Season", "Round", "team_pace_asof_s"]], on=["Team", "Season", "Round"], how="left"
    )

    history["driver_vs_teammate_asof_s"] = (
        history.groupby("Driver")["teammate_gap_s"]
        .transform(lambda s: s.shift(1).ewm(halflife=halflife_events, min_periods=1).mean())
    )
    return history
