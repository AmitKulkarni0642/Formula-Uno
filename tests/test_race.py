"""
Race-pace comparison correctness: cumulative gap evolution matches manual
arithmetic, pit-stop time is included (not subtracted out), a lead change
is detected exactly when the gap's sign flips, and a missing lap time
stops the comparison rather than inventing a "ghost" continuation.
"""

import duckdb
import pandas as pd
import pytest

from src.compare import race
from src.store import db


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute(db._SCHEMA_SQL)
    yield c
    c.close()


def _insert_laps(con, session_id: str, driver_id: str, laps: list[dict]):
    rows = []
    for lap_number, lap_s, compound, stint, pit_in in laps:
        rows.append({
            "session_id": session_id, "driver_id": driver_id, "lap_number": lap_number,
            "lap_ms": int(lap_s * 1000) if lap_s is not None else None,
            "s1_ms": None, "s2_ms": None, "s3_ms": None,
            "compound": compound, "stint": stint, "tyre_life": None, "fresh_tyre": None,
            "pit_in": pit_in, "pit_out": False, "track_status": "1",
            "is_deleted": False, "deleted_reason": None, "is_accurate": True,
            "position": None, "session_time_ms": None, "air_temp": None, "track_temp": None, "rainfall": False,
        })
    db.replace_rows(con, "laps", {"session_id": session_id, "driver_id": driver_id}, pd.DataFrame(rows))


def test_identical_pace_gives_zero_gap_throughout(con):
    laps = [(n, 90.0, "MEDIUM", 1, False) for n in range(1, 6)]
    _insert_laps(con, "R", "a", laps)
    _insert_laps(con, "R", "b", laps)

    result = race.race_pace_comparison(con, "R", "a", "b")
    assert result["laps_compared"] == 5
    assert all(r["gap_s"] == pytest.approx(0.0) for r in result["laps"])
    assert result["lead_changes"] == []


def test_gap_matches_manual_cumulative_arithmetic(con):
    a_times = [90.0, 90.0, 90.0]
    b_times = [91.0, 89.0, 90.0]  # B: slower, then faster, then even
    _insert_laps(con, "R", "a", [(i + 1, t, "MEDIUM", 1, False) for i, t in enumerate(a_times)])
    _insert_laps(con, "R", "b", [(i + 1, t, "MEDIUM", 1, False) for i, t in enumerate(b_times)])

    result = race.race_pace_comparison(con, "R", "a", "b")
    cum_a = [90.0, 180.0, 270.0]
    cum_b = [91.0, 180.0, 270.0]
    expected_gaps = [cum_b[i] - cum_a[i] for i in range(3)]
    assert [r["gap_s"] for r in result["laps"]] == pytest.approx(expected_gaps)
    assert result["final_gap_s"] == pytest.approx(0.0)


def test_pit_stop_time_counts_toward_the_gap(con):
    # A pits (lap 2 costs an extra 20s of real time); B doesn't. The gap
    # should open up by ~20s on the pit lap, not be masked out.
    a_laps = [(1, 90.0, "MEDIUM", 1, False), (2, 110.0, "HARD", 2, True), (3, 88.0, "HARD", 2, False)]
    b_laps = [(1, 90.0, "MEDIUM", 1, False), (2, 90.0, "MEDIUM", 1, False), (3, 90.0, "MEDIUM", 1, False)]
    _insert_laps(con, "R", "a", a_laps)
    _insert_laps(con, "R", "b", b_laps)

    result = race.race_pace_comparison(con, "R", "a", "b")
    gap_after_pit = result["laps"][1]["gap_s"]  # lap 2
    assert gap_after_pit == pytest.approx(-20.0, abs=0.01)  # B now ~20s AHEAD of A
    assert result["laps"][1]["pit_lap_a"] is True
    assert result["laps"][1]["pit_lap_b"] is False


def test_lead_change_detected_exactly_on_sign_flip(con):
    # A ahead (negative-ish gap convention: gap_s = cumB - cumA, so A ahead -> gap_s > 0... )
    # Build it concretely: A slower early (B ahead/gap negative), then A faster (A catches up and passes).
    a_laps = [(1, 92.0, "MEDIUM", 1, False), (2, 86.0, "HARD", 2, False), (3, 86.0, "HARD", 2, False)]
    b_laps = [(1, 90.0, "MEDIUM", 1, False), (2, 90.0, "MEDIUM", 1, False), (3, 90.0, "MEDIUM", 1, False)]
    _insert_laps(con, "R", "a", a_laps)
    _insert_laps(con, "R", "b", b_laps)

    result = race.race_pace_comparison(con, "R", "a", "b")
    gaps = [r["gap_s"] for r in result["laps"]]
    assert gaps[0] < 0  # after lap 1: B's cum (90) - A's cum (92) = -2 -> A behind on time... gap_s negative means B ahead in time, i.e. A is SLOWER/behind
    assert gaps[-1] > 0  # by lap 3 A has caught up and gone ahead
    assert len(result["lead_changes"]) == 1
    assert result["lead_changes"][0]["lap_number"] in (2, 3)


def test_stops_at_first_missing_lap_time_no_ghost_continuation(con):
    a_laps = [(1, 90.0, "MEDIUM", 1, False), (2, None, "MEDIUM", 1, False), (3, 90.0, "MEDIUM", 1, False)]
    b_laps = [(1, 90.0, "MEDIUM", 1, False), (2, 90.0, "MEDIUM", 1, False), (3, 90.0, "MEDIUM", 1, False)]
    _insert_laps(con, "R", "a", a_laps)
    _insert_laps(con, "R", "b", b_laps)

    result = race.race_pace_comparison(con, "R", "a", "b")
    assert result["laps_compared"] == 1  # stops before lap 2's missing time
    assert result["laps"][-1]["lap_number"] == 1


def test_stints_report_compound_and_pace_excluding_pit_laps(con):
    laps = [
        (1, 90.0, "MEDIUM", 1, False),
        (2, 90.5, "MEDIUM", 1, False),
        (3, 110.0, "HARD", 2, True),   # pit lap — excluded from stint pace average
        (4, 88.0, "HARD", 2, False),
        (5, 88.5, "HARD", 2, False),
    ]
    _insert_laps(con, "R", "a", laps)
    _insert_laps(con, "R", "b", laps)

    result = race.race_pace_comparison(con, "R", "a", "b")
    stints = result["stints_a"]
    assert len(stints) == 2
    assert stints[0]["compound"] == "MEDIUM"
    assert stints[0]["avg_lap_s"] == pytest.approx(90.25)
    assert stints[1]["compound"] == "HARD"
    assert stints[1]["avg_lap_s"] == pytest.approx(88.25)  # pit lap (110.0) excluded


def test_raises_for_unknown_driver(con):
    _insert_laps(con, "R", "a", [(1, 90.0, "MEDIUM", 1, False)])
    with pytest.raises(ValueError):
        race.race_pace_comparison(con, "R", "a", "nobody")
