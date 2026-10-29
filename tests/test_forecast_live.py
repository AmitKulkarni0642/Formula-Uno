"""
Correctness of the 'current form' snapshot used to forecast an event that
hasn't happened yet: _ewm_latest() must equal exactly what rolling_pace_asof's
shift(1)-then-EWM would produce FOR a hypothetical next row, appended to the
real history -- since that hypothetical row's own value gets shifted away
regardless of what it is. Synthetic data only, no network.
"""

import pandas as pd

from src.forecast.live import _ewm_latest
from src.forecast.pace import rolling_pace_asof


def _history_row(season, rnd, team, driver, gap, teammate_gap=0.0):
    return {
        "Season": season, "Round": rnd,
        "EventDate": pd.Timestamp(year=season, month=1, day=1) + pd.Timedelta(days=14 * rnd),
        "Team": team, "Driver": driver,
        "gap_to_fastest_s": gap, "teammate_gap_s": teammate_gap,
    }


def test_ewm_latest_matches_the_asof_value_a_hypothetical_next_row_would_get():
    rows = [_history_row(2024, r, "mercedes", "HAM", 0.3 + 0.05 * r) for r in range(1, 5)]
    history = pd.DataFrame(rows)

    # What rolling_pace_asof computes for a hypothetical round-5 row, whatever
    # placeholder value that row carries for its OWN gap (shift(1) drops it).
    hypothetical = pd.concat([history, pd.DataFrame([_history_row(2024, 5, "mercedes", "HAM", 999.0)])],
                              ignore_index=True)
    asof_for_round5 = rolling_pace_asof(hypothetical)
    expected = asof_for_round5[asof_for_round5["Round"] == 5]["team_pace_asof_s"].iloc[0]

    actual = _ewm_latest(history["gap_to_fastest_s"])
    assert abs(actual - expected) < 1e-9


def test_ewm_latest_is_nan_for_empty_series():
    assert pd.isna(_ewm_latest(pd.Series([], dtype=float)))


def test_ewm_latest_ignores_nan_rows():
    s = pd.Series([1.0, float("nan"), 1.0, 1.0])
    assert _ewm_latest(s) == 1.0
