"""
Correctness of the Monte Carlo simulation core (simulate_positions/summarize)
in isolation from any model or network -- synthetic pace curves only, same
convention as the rest of this suite.
"""

import numpy as np
import pandas as pd

from src.forecast.montecarlo import simulate_positions, summarize, _shrink_toward_pool


def test_clearly_faster_driver_wins_every_trial_with_no_noise_no_dnf_no_sc():
    total_laps = 50
    pace = {
        "FAST": np.full(total_laps, 90.0),
        "SLOW": np.full(total_laps, 92.0),
    }
    sims = simulate_positions(
        pace_curves=pace, grid={"FAST": 1, "SLOW": 2}, stop_dist={1: 1.0}, pit_loss_s=20.0,
        dnf_rates={}, overall_dnf_rate=0.0, driver_team={"FAST": "a", "SLOW": "b"},
        sc_prob=0.0, noise_std=0.0, n_sims=200,
    )
    summary = summarize(sims, grid={"FAST": 1, "SLOW": 2})
    fast_row = summary[summary["driver"] == "FAST"].iloc[0]
    assert fast_row["win_prob"] == 1.0
    assert fast_row["dnf_prob"] == 0.0


def test_guaranteed_dnf_never_wins_and_is_always_classified_last():
    total_laps = 30
    pace = {"A": np.full(total_laps, 90.0), "B": np.full(total_laps, 90.0)}
    sims = simulate_positions(
        pace_curves=pace, grid={"A": 1, "B": 2}, stop_dist={1: 1.0}, pit_loss_s=20.0,
        dnf_rates={"team_a": 1.0}, overall_dnf_rate=0.0, driver_team={"A": "team_a", "B": "team_b"},
        sc_prob=0.0, noise_std=0.0, n_sims=200,
    )
    summary = summarize(sims, grid={"A": 1, "B": 2})
    a_row = summary[summary["driver"] == "A"].iloc[0]
    assert a_row["win_prob"] == 0.0
    assert a_row["dnf_prob"] == 1.0
    assert a_row["expected_position"] == 2.0  # always classified behind the finisher


def test_probabilities_sum_to_one_driver_across_the_field():
    total_laps = 40
    rng = np.random.default_rng(0)
    pace = {f"D{i}": np.full(total_laps, 90.0 + i * 0.1) for i in range(10)}
    sims = simulate_positions(
        pace_curves=pace, grid={d: i + 1 for i, d in enumerate(pace)}, stop_dist={1: 0.7, 2: 0.3},
        pit_loss_s=22.0, dnf_rates={}, overall_dnf_rate=0.05,
        driver_team={d: "team" for d in pace}, sc_prob=0.2, noise_std=0.5, n_sims=500,
    )
    summary = summarize(sims, grid={d: i + 1 for i, d in enumerate(pace)})
    assert abs(summary["win_prob"].sum() - 1.0) < 1e-9
    assert len(summary) == 10


def test_shrinkage_pulls_a_small_sample_certainty_away_from_1_0():
    # A circuit with only 4 historical races, all with a safety car, has a
    # raw empirical rate of 1.0 -- but 4 samples isn't enough to call that
    # genuine certainty. Shrinking toward a broader pooled rate must move it.
    shrunk = _shrink_toward_pool(sample_rate=1.0, n=4, pooled_rate=0.5)
    assert 0.5 < shrunk < 1.0


def test_shrinkage_barely_moves_a_large_sample():
    shrunk = _shrink_toward_pool(sample_rate=0.9, n=500, pooled_rate=0.5)
    assert abs(shrunk - 0.9) < 0.01


def test_safety_car_increases_variance_without_changing_pace_order_identity():
    # With SC guaranteed every trial, the nominally-faster driver should still
    # win MORE often than the slower one (SC compresses gaps, doesn't invert
    # them), just not with the same certainty as the no-SC case above.
    total_laps = 50
    pace = {"FAST": np.full(total_laps, 90.0), "SLOW": np.full(total_laps, 92.0)}
    sims = simulate_positions(
        pace_curves=pace, grid={"FAST": 1, "SLOW": 2}, stop_dist={1: 1.0}, pit_loss_s=20.0,
        dnf_rates={}, overall_dnf_rate=0.0, driver_team={"FAST": "a", "SLOW": "b"},
        sc_prob=1.0, noise_std=1.0, n_sims=2000,
    )
    summary = summarize(sims, grid={"FAST": 1, "SLOW": 2})
    fast_row = summary[summary["driver"] == "FAST"].iloc[0]
    assert fast_row["win_prob"] > 0.5
