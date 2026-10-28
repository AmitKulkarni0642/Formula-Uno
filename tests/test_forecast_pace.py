"""
Leakage-safety and correctness of the Phase 4 rolling pace features, per
PLAN.md section 7. Synthetic history only — no network, no FastF1 session
loads — mirroring the rest of this test suite's convention.
"""

import numpy as np
import pandas as pd

from src.forecast.pace import rolling_pace_asof
from src.forecast.schedule import events_before


def _history_row(season, rnd, team, driver, gap, teammate_gap):
    return {
        "Season": season, "Round": rnd,
        "EventDate": pd.Timestamp(year=season, month=1, day=1) + pd.Timedelta(days=14 * rnd),
        "Team": team, "Driver": driver,
        "gap_to_fastest_s": gap, "teammate_gap_s": teammate_gap,
    }


def test_first_appearance_has_no_rolling_value():
    history = pd.DataFrame([_history_row(2024, 1, "red_bull", "VER", 0.0, -0.1)])
    out = rolling_pace_asof(history)
    assert pd.isna(out.loc[0, "team_pace_asof_s"])
    assert pd.isna(out.loc[0, "driver_vs_teammate_asof_s"])


def test_rolling_value_never_uses_its_own_row():
    # A team that was 1s off pace every round, then suddenly 0.0s in round 4 —
    # round 4's OWN feature must reflect only rounds 1-3 (i.e. still ~1.0),
    # not be dragged toward 0 by its own result.
    rows = [_history_row(2024, r, "ferrari", "LEC", 1.0, 0.0) for r in range(1, 4)]
    rows.append(_history_row(2024, 4, "ferrari", "LEC", 0.0, 0.0))
    history = pd.DataFrame(rows)
    out = rolling_pace_asof(history)
    assert out.loc[3, "team_pace_asof_s"] == 1.0  # purely from rounds 1-3, unaffected by round 4's 0.0


def test_rolling_value_is_monotone_between_two_constant_regimes():
    # Pace improves from 1.0s off to 0.3s off after round 3; the as-of value
    # should move toward the new regime but lag it (EWM, not an instant jump).
    rows = [_history_row(2024, r, "mclaren", "NOR", 1.0, 0.0) for r in range(1, 4)]
    rows += [_history_row(2024, r, "mclaren", "NOR", 0.3, 0.0) for r in range(4, 7)]
    history = pd.DataFrame(rows)
    out = rolling_pace_asof(history)
    asof = out["team_pace_asof_s"].to_numpy()
    # round 4's feature (index 3) still reflects the OLD regime only
    assert asof[3] == 1.0
    # by round 6 (index 5) it has moved toward the new regime but not fully there
    assert 0.3 < asof[5] < 1.0


def test_team_lineage_is_not_cross_contaminated():
    # Two unrelated teams must never see each other's rolling average.
    rows = [_history_row(2024, r, "red_bull", "VER", 0.0, 0.0) for r in range(1, 4)]
    rows += [_history_row(2024, r, "williams", "ALB", 2.0, 0.0) for r in range(1, 4)]
    history = pd.DataFrame(rows)
    out = rolling_pace_asof(history)
    rb_final = out[(out["Team"] == "red_bull") & (out["Round"] == 3)]["team_pace_asof_s"].iloc[0]
    wi_final = out[(out["Team"] == "williams") & (out["Round"] == 3)]["team_pace_asof_s"].iloc[0]
    assert rb_final == 0.0
    assert wi_final == 2.0


def test_teammates_share_the_same_team_asof_value():
    # Two drivers at the same team, same round, must see the identical
    # team_pace_asof_s — it's a property of the CAR, not of whichever driver's
    # row happens to land next to it in the frame.
    rows = []
    for r in range(1, 4):
        rows.append(_history_row(2024, r, "mercedes", "HAM", 0.5 + 0.1 * r, 0.0))
        rows.append(_history_row(2024, r, "mercedes", "RUS", 0.5 + 0.1 * r, 0.0))
    history = pd.DataFrame(rows)
    out = rolling_pace_asof(history)
    round3 = out[out["Round"] == 3]
    values = round3["team_pace_asof_s"].unique()
    assert len(values) == 1, f"teammates disagree on team pace: {round3[['Driver', 'team_pace_asof_s']]}"


def test_events_before_is_a_strict_chronological_prefix():
    events = pd.DataFrame({
        "Season": [2023, 2023, 2024, 2024],
        "Round": [20, 21, 1, 2],
        "EventName": ["a", "b", "c", "d"],
    })
    before = events_before(events, season=2024, round_=2)
    assert list(before["EventName"]) == ["a", "b", "c"]
    assert "d" not in before["EventName"].tolist()
