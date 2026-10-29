"""
Orchestrates everything in src/forecast/ into one call: forecast an event
that hasn't happened yet (the user's "second set" -- e.g. the upcoming
Mexico City GP), end to end.

Strategy/compound choice is deliberately simple (fixed representative
1-stop / 2-stop compound sequences, pit laps at historically-typical
fractions of the race) rather than its own learned model -- PLAN.md's own
cut line puts a dedicated strategy model behind the Monte Carlo simulator
and backtests if time is short, and it is. The Monte Carlo layer still
samples stop COUNT from this circuit's real historical distribution, which
is where the actual strategy-driven variance (the Hamilton/Barcelona
two-stop story the user opened this whole phase with) comes from.
"""

import datetime as dt

import numpy as np
import pandas as pd

from src.ingestion.load_session import load_race
from src.store.ids import era_for_season
from src.forecast import schedule, live, montecarlo, weather
from src.forecast.features import COMPOUND_ORDER, ERA_ORDER, FIRST_SEASON
from src.forecast.infer import LoadedLapTimeModel
from src.store.ids import circuit_key as circuit_key_of

RACE_MODEL_NAME = "nn_laptime_r_2022_2023_2024"
QUALI_MODEL_NAME = "nn_laptime_q_2022_2023_2024"


def _era_encoded(season: int) -> int:
    return ERA_ORDER[era_for_season(season)]


def _base_row(pace_snap: dict, track_snap: dict, driver: str, team: str, wx: dict, season: int) -> dict:
    return {
        "team_pace_asof_s": pace_snap["team_pace"].get(team, np.nan),
        "driver_vs_teammate_asof_s": pace_snap["driver_vs_teammate"].get(driver, np.nan),
        "typical_laptime_s_asof": track_snap.get("typical_laptime_s_asof", np.nan),
        "power_sensitivity_kmh_asof": track_snap.get("power_sensitivity_kmh_asof", np.nan),
        "degradation_s_per_lap_asof": track_snap.get("degradation_s_per_lap_asof", np.nan),
        "position_change_rate_asof": track_snap.get("position_change_rate_asof", np.nan),
        "TrackTemp": wx["TrackTemp"], "AirTemp": wx["AirTemp"],
        "YearsSinceStart": float(season - FIRST_SEASON),
        "EraEncoded": _era_encoded(season),
    }


def predict_grid(roster: pd.DataFrame, pace_snap: dict, track_snap: dict, wx: dict, season: int) -> pd.DataFrame:
    """Predicted qualifying order -- no GridPosition feature (see features.py docstring: that was the old leak)."""
    quali_model = LoadedLapTimeModel(QUALI_MODEL_NAME)
    rows = []
    for _, r in roster.iterrows():
        row = _base_row(pace_snap, track_snap, r["Abbreviation"], r["Team"], wx, season)
        row.update({
            "TyreLife": 2.0, "TyreLifeSquared": 4.0, "FuelLoad": 5.0,
            "LapNumber": 12.0,  # representative -- qualifying best laps cluster mid-session (Q2/Q3 runs)
            "CompoundEncoded": COMPOUND_ORDER["SOFT"],
        })
        rows.append(row)
    X = pd.DataFrame(rows)
    pred = quali_model.predict(X)
    out = roster[["Abbreviation", "Team"]].copy()
    out["predicted_quali_s"] = pred
    out["grid"] = out["predicted_quali_s"].rank(method="min").astype(int)
    return out.sort_values("grid").reset_index(drop=True)


_STRATEGIES = {
    1: [("MEDIUM", 0.5)],                          # one stop, roughly mid-race -- (compound, pit_fraction)
    2: [("SOFT", 0.33), ("MEDIUM", 0.66)],         # two stops
}
_FINAL_COMPOUND = "HARD"


def pace_curve(race_model: LoadedLapTimeModel, base_row: dict, grid_pos: int, total_laps: int, stops: list) -> np.ndarray:
    """
    Predicted lap time for every lap of the race under one strategy. `stops`
    is a list of (compound, pit_lap) for every stint boundary AFTER the
    first; the first stint's compound is always the first entry's.
    """
    boundaries = [1] + [p[1] for p in stops] + [total_laps + 1]
    stint_compounds = [c for c, _ in stops] + [_FINAL_COMPOUND]

    rows = []
    for lap in range(1, total_laps + 1):
        stint_idx = next(i for i in range(len(boundaries) - 1) if boundaries[i] <= lap < boundaries[i + 1])
        tyre_age = lap - boundaries[stint_idx] + 1
        compound = stint_compounds[stint_idx]
        fuel = 105.0 - (lap - 1) * (105.0 / total_laps)
        row = dict(base_row)
        row.update({
            "TyreLife": float(tyre_age), "TyreLifeSquared": float(tyre_age) ** 2,
            "FuelLoad": fuel, "LapNumber": float(lap), "GridPosition": float(grid_pos),
            "CompoundEncoded": COMPOUND_ORDER.get(compound, 1),
        })
        rows.append(row)
    X = pd.DataFrame(rows)
    return race_model.predict(X)


def forecast_event(season: int, round_: int, n_sims: int = 5000, history_start_season: int = 2022) -> dict:
    events = schedule.all_events(history_start_season, season)
    this_event = events[(events["Season"] == season) & (events["Round"] == round_)].iloc[0]
    circuit = circuit_key_of(str(this_event["Location"]))
    prior_circuit_events = events[
        (events["Season"] * 100 + events["Round"] < season * 100 + round_)
    ]
    circuit_events = prior_circuit_events[
        prior_circuit_events.apply(lambda r: circuit_key_of(str(r["Location"])) == circuit, axis=1)
    ]

    roster = live.current_roster(season, round_)
    pace_snap = live.snapshot_pace(history_start_season, season, round_, "R")
    track_snap = live.snapshot_track(history_start_season, season, round_, "R", circuit)

    session_utc = pd.Timestamp(this_event["EventDate"]).replace(hour=20)  # approx race-time UTC; refined below if available
    wx = weather.forecast_session_weather(circuit, circuit_events, session_utc)

    grid_df = predict_grid(roster, pace_snap, track_snap, wx, season)
    grid_map = dict(zip(grid_df["Abbreviation"], grid_df["grid"]))
    team_map = dict(zip(roster["Abbreviation"], roster["Team"]))

    # Race distance: most recent prior race at this circuit, else a generic default.
    total_laps = 71
    for _, ev in circuit_events.sort_values("EventDate", ascending=False).iterrows():
        try:
            total_laps = int(load_race(int(ev["Season"]), int(ev["Round"]))["laps"]["LapNumber"].max())
            break
        except Exception:
            continue

    race_model = LoadedLapTimeModel(RACE_MODEL_NAME)
    pace_curves: dict[str, np.ndarray] = {}
    for _, r in roster.iterrows():
        driver = r["Abbreviation"]
        base = _base_row(pace_snap, track_snap, driver, r["Team"], wx, season)
        strat = [(c, int(round(frac * total_laps))) for c, frac in _STRATEGIES[2]]
        pace_curves[driver] = pace_curve(race_model, base, grid_map.get(driver, 20), total_laps, strat)

    recent_events = events[events["Season"] >= season - 2]
    stop_dist = montecarlo.historical_stop_counts(circuit_events)
    dnf_rates, overall_dnf = montecarlo.team_dnf_rates(recent_events)
    sc_prob = montecarlo.safety_car_probability(circuit_events, pooled_events=recent_events)
    pit_loss = montecarlo.pit_loss_estimate(circuit_events)
    noise_std = montecarlo.lap_to_lap_noise_std(circuit_events)

    sims = montecarlo.simulate_positions(
        pace_curves=pace_curves, grid=grid_map, stop_dist=stop_dist, pit_loss_s=pit_loss,
        dnf_rates=dnf_rates, overall_dnf_rate=overall_dnf, driver_team=team_map,
        sc_prob=sc_prob, noise_std=noise_std, n_sims=n_sims,
    )
    summary = montecarlo.summarize(sims, grid_map)

    return {
        "event": str(this_event["EventName"]), "season": season, "round": round_,
        "circuit": circuit, "total_laps": total_laps, "weather": wx,
        "stop_dist": stop_dist, "sc_prob": sc_prob, "pit_loss_s": pit_loss, "noise_std_s": noise_std,
        "predicted_grid": grid_df, "race_forecast": summary,
    }
