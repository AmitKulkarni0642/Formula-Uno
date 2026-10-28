"""
Compute layer for the prediction API.

This module is deliberately separate from the web layer (app.py). Its job is:
  load artifacts (encoders + trained model)  ->  simulate a race  ->  return a plain dict.

Keeping "compute" separate from "transport" (HTTP) means the same predict_race()
function can be reused later by the Streamlit frontend (Stage 2), the RAG assistant
(Stage 3), and the agent tool (Stage 4) — none of them should have to know about HTTP.
"""

import pandas as pd
from src.ingestion.load_session import load_race, load_qualifying
from src.features.build_features import build_encoders, temp_bounds, FEATURE_COLS
from src.model.train import load_model, save_model
from src.engine.race_engine import RaceEngine
from src.analytics.compare import compare_positions, lap_time_rmse, final_classification
from src.analytics.qualifying import extract_best_qualifying_laps, predict_qualifying


# The years the Bahrain model was trained on, and the full span we can serve.
TRAIN_YEARS = [2022, 2023, 2024]
SERVE_YEARS = [2022, 2023, 2024, 2025]

# Registry of circuits that currently have a persisted model on disk.
CIRCUITS = {
    "bahrain": {
        "label": "Bahrain",
        "event": "Bahrain Grand Prix",
        "model": "laptime_bahrain_2022_2023_2024",
    },
    "spa": {
        "label": "Spa",
        "event": "Belgian Grand Prix",
        "model": "laptime_spa_2022_2023_2024",
    },
    "austria": {
        "label": "Austria",
        "event": "Austrian Grand Prix",
        "model": "laptime_austria_2022_2023_2024",
    },
    "australia": {
        "label": "Australia",
        "event": "Australian Grand Prix",
        "model": "laptime_australia_2022_2023_2024",
    },
    "monza": {
        "label": "Monza",
        "event": "Italian Grand Prix",
        "model": "laptime_monza_2022_2023_2024",
    },
    "abudhabi": {
        "label": "AbuDhabi",
        "event": "Abu Dhabi Grand Prix",
        "model": "laptime_abudhabi_2022_2023_2024",
    },
    "mexico": {
        "label": "Mexico",
        "event": "Mexico City Grand Prix",
        "model": "laptime_mexico_2022_2023_2024",
    },
    "monaco": {
        "label": "Monaco",
        "event": "Monaco Grand Prix",
        "model": "laptime_monaco_2022_2023_2024",
    },
    "canada": {
        "label": "Canada",
        "event": "Canadian Grand Prix",
        "model": "laptime_canada_2022_2023_2024",
    },
    "silverstone": {
        "label": "Silverstone",
        "event": "British Grand Prix",
        "model": "laptime_silverstone_2022_2023_2024",
    },
}

# In-process caches so repeated requests are cheap.
_artifact_cache: dict = {}   # circuit_key -> {"encoders":..., "model":...}
_result_cache: dict = {}     # (circuit_key, year) -> response dict

# Hybrid qualifying: data-thin circuits use the pooled model (it learns the development
# trend from the clean circuits), the rest use their specialized model.
# Spa's specialized qual data is too thin/contaminated (wet 2024 removed, damp 2023).
_POOL_TRACK_STR = "bahrain_spa_austria_australia_monza_abudhabi_mexico_monaco_canada_silverstone"
_POOL_YEAR_STR = "2022_2023_2024"
COMBINED_QUAL_MODEL = f"qualtime_multi_{_POOL_TRACK_STR}_{_POOL_YEAR_STR}"
# Spa was pooled here through the 6-circuit model (1.19s, a real fix). Adding Mexico/
# Monaco to the 8-circuit pool broke it badly (13.8s, worse than solo) — see the
# TrackEncoded finding below. Reverted to specialized until that's fixed properly.
USE_COMBINED_QUAL: set = set()
_combined_qual_cache: dict = {}

# Hybrid race: Monaco's specialized race data is thin — 2022/2023 were wet races, so
# wet-lap filtering drops 51% and 33% of those years, leaving barely one clean year.
# Route it through the pooled race model instead, same rescue as Spa's qualifying.
COMBINED_RACE_MODEL = f"laptime_multi_{_POOL_TRACK_STR}_{_POOL_YEAR_STR}"
# Monaco was pooled here, but that was decided on a flawed comparison (specialized's
# CV RMSE 3.476s vs pooled's true out-of-sample 3.052s — not apples to apples). The
# correct comparison is specialized's OWN true out-of-sample RMSE, 2.396s, which beats
# the pooled model's 3.052s. Reverted to specialized.
USE_COMBINED_RACE: set = set()
_combined_race_cache: dict = {}


def available_circuits() -> list[dict]:
    """
    List circuits the API can currently serve. `event` (the exact FastF1 event
    name) lets a caller that only knows an event name — e.g. the event-page
    Preview tab, which gets there via /schedule — look up whether a circuit
    key, and therefore a prediction, exists for it at all.
    """
    return [{"key": k, "label": v["label"], "event": v["event"]} for k, v in CIRCUITS.items()]


def _get_artifacts(circuit_key: str) -> dict:
    """
    Load (and cache) the encoders and trained model for a circuit.

    Encoders + temp_bounds are persisted to disk as "encoders_<circuit>_<years>.pkl",
    a write-through cache: the first call that can't find the file rebuilds it from
    FastF1 sessions (slow — this is what used to happen on EVERY cold start) and saves
    the result, so every call after — including in a fresh process — loads the pickle
    directly. Because the encoders are rebuilt deterministically (LabelEncoder.fit on
    a sorted session union) the very first build still reproduces the identical integer
    codes the model was trained with, so training-serving symmetry holds either way.
    """
    if circuit_key in _artifact_cache:
        return _artifact_cache[circuit_key]

    circ = CIRCUITS[circuit_key]
    label, event = circ["label"], circ["event"]
    encoder_artifact = circ["model"].replace("laptime_", "encoders_", 1)

    try:
        persisted = load_model(encoder_artifact)
        encoders, bounds = persisted["encoders"], persisted["temp_bounds"]
    except FileNotFoundError:
        sessions = []
        train_race_laps = []
        for yr in SERVE_YEARS:
            race_laps = load_race(yr, event)["laps"]
            sessions.append({"laps": race_laps, "track_name": label})
            sessions.append({"laps": load_qualifying(yr, event)["laps"], "track_name": label})
            if yr in TRAIN_YEARS:
                train_race_laps.append(race_laps)
        encoders = build_encoders(sessions)
        bounds = temp_bounds(pd.concat(train_race_laps)) if train_race_laps else {}
        save_model({"encoders": encoders, "temp_bounds": bounds}, encoder_artifact)

    model = load_model(circ["model"])
    qual_model = load_model(circ["model"].replace("laptime_", "qualtime_"))

    _artifact_cache[circuit_key] = {
        "encoders": encoders, "model": model, "qual_model": qual_model, "temp_bounds": bounds,
    }
    return _artifact_cache[circuit_key]


_POOL_ARTIFACTS_NAME = f"pool_artifacts_{_POOL_TRACK_STR}_{_POOL_YEAR_STR}"
_pool_cache: dict = {}


def _get_pool_artifacts() -> dict:
    """
    Load (and cache) the shared pooled encoders + track_enc + temp_bounds spanning every
    circuit. Same write-through disk cache as _get_artifacts. Shared by both the pooled
    race and pooled qualifying paths — previously each rebuilt this independently (a
    64-session reload, done twice), which this also removes.
    """
    if _pool_cache:
        return _pool_cache

    try:
        _pool_cache.update(load_model(_POOL_ARTIFACTS_NAME))
        return _pool_cache
    except FileNotFoundError:
        pass

    sessions = []
    train_race_laps = []
    for circ in CIRCUITS.values():
        for yr in SERVE_YEARS:
            race_laps = load_race(yr, circ["event"])["laps"]
            sessions.append({"laps": race_laps, "track_name": circ["label"]})
            sessions.append({"laps": load_qualifying(yr, circ["event"])["laps"], "track_name": circ["label"]})
            if yr in TRAIN_YEARS:
                train_race_laps.append(race_laps)
    encoders = build_encoders(sessions)
    track_enc = {lbl: int(encoders["Track"].transform([lbl])[0]) for lbl in encoders["Track"].classes_}
    bounds = temp_bounds(pd.concat(train_race_laps)) if train_race_laps else {}

    _pool_cache.update({"encoders": encoders, "track_enc": track_enc, "temp_bounds": bounds})
    save_model(dict(_pool_cache), _POOL_ARTIFACTS_NAME)
    return _pool_cache


def _get_combined_race() -> dict:
    """Load (and cache) the pooled race model, reusing the shared pool artifacts."""
    if _combined_race_cache:
        return _combined_race_cache
    pool = _get_pool_artifacts()
    _combined_race_cache.update({
        "encoders": pool["encoders"],
        "model": load_model(COMBINED_RACE_MODEL),
        "track_enc": pool["track_enc"],
        "temp_bounds": pool["temp_bounds"],
    })
    return _combined_race_cache


def predict_race(circuit_key: str, year: int, use_cache: bool = True) -> dict:
    """
    Simulate a circuit's race for a given year and return structured results.

    Hybrid model choice: data-thin circuits (USE_COMBINED_RACE) use the pooled model,
    which learns car/driver pace from the full multi-circuit dataset instead of a
    circuit with too few clean training laps of its own. Everyone else uses their
    specialized, circuit-only model.

    Returns a JSON-serializable dict: circuit/year metadata, summary metrics, and the
    predicted finishing order with per-driver actual-vs-simulated comparison.
    """
    circuit_key = circuit_key.lower()
    if circuit_key not in CIRCUITS:
        raise KeyError(f"Unknown circuit '{circuit_key}'. Available: {list(CIRCUITS)}")
    if year not in SERVE_YEARS:
        raise ValueError(f"Year {year} not servable for {circuit_key}. Available: {SERVE_YEARS}")

    cache_key = (circuit_key, year)
    if use_cache and cache_key in _result_cache:
        return _result_cache[cache_key]

    circ = CIRCUITS[circuit_key]
    race = load_race(year, circ["event"])

    if circuit_key in USE_COMBINED_RACE:
        art = _get_combined_race()
        engine = RaceEngine(
            art["model"], art["encoders"], FEATURE_COLS,
            track_encoded=art["track_enc"][circ["label"]], sim_year=year, temp_bounds=art["temp_bounds"],
        )
        model_name, approach = COMBINED_RACE_MODEL, "pooled (thin specialized data)"
    else:
        art = _get_artifacts(circuit_key)
        engine = RaceEngine(
            art["model"], art["encoders"], FEATURE_COLS,
            track_encoded=0, sim_year=year, temp_bounds=art["temp_bounds"],
        )
        model_name, approach = circ["model"], "specialized"

    sim = engine.simulate(race["laps"], race["results"])

    # Reuse the analytics layer rather than reimplementing metrics.
    comp = compare_positions(sim, race["results"])   # Driver, SimPos, ActualPos, Error
    rmse = lap_time_rmse(sim, race["laps"])           # index Driver -> RMSE, Laps
    final = final_classification(sim)                 # Position, Driver, Team, CumulativeTime

    team_map = dict(zip(final["Driver"], final["Team"]))
    cumu_map = dict(zip(final["Driver"], final["CumulativeTime"]))
    rmse_map = rmse["RMSE"].to_dict()

    results = []
    for _, row in comp.sort_values("SimPos").iterrows():
        drv = row["Driver"]
        results.append({
            "sim_position":     int(row["SimPos"]),
            "driver":           drv,
            "team":             team_map.get(drv),
            "cumulative_time_s": round(float(cumu_map.get(drv, 0.0)), 3),
            "actual_position":  int(row["ActualPos"]),
            "position_error":   int(row["Error"]),
            "lap_rmse_s":       round(float(rmse_map[drv]), 3) if drv in rmse_map else None,
        })

    fleet_rmse = float((rmse["RMSE"] ** 2).mean() ** 0.5) if len(rmse) else None
    metrics = {
        "mean_position_error": round(float(comp["Error"].mean()), 3),
        "exact_positions":     int((comp["Error"] == 0).sum()),
        "within_2_positions":  int((comp["Error"] <= 2).sum()),
        "drivers_compared":    int(len(comp)),
        "fleet_lap_rmse_s":    round(fleet_rmse, 3) if fleet_rmse is not None else None,
    }

    response = {
        "circuit":   circ["label"],
        "year":      year,
        "model":     model_name,
        "approach":  approach,
        "in_sample": year in TRAIN_YEARS,
        "metrics":   metrics,
        "results":   results,
    }
    _result_cache[cache_key] = response
    return response


def get_lap_trace(circuit_key: str, year: int, driver: str) -> dict:
    """
    Per-lap detail for one driver that predict_race() aggregates away: lap time,
    running position, and gap to the race leader — predicted vs. actual, lap by
    lap. One simulation produces all three series together (cheaper than three
    separate calls). Re-simulates rather than reusing a cached predict_race()
    result, so it's correct even if called first.

    A lap missing on one side (a driver who retired, or a lap FastF1 couldn't time
    cleanly) shows as a gap in that series, never a guessed value.
    """
    circuit_key = circuit_key.lower()
    if circuit_key not in CIRCUITS:
        raise KeyError(f"Unknown circuit '{circuit_key}'. Available: {list(CIRCUITS)}")
    if year not in SERVE_YEARS:
        raise ValueError(f"Year {year} not servable for {circuit_key}. Available: {SERVE_YEARS}")

    circ = CIRCUITS[circuit_key]
    race = load_race(year, circ["event"])

    if circuit_key in USE_COMBINED_RACE:
        art = _get_combined_race()
        engine = RaceEngine(art["model"], art["encoders"], FEATURE_COLS,
                            track_encoded=art["track_enc"][circ["label"]], sim_year=year,
                            temp_bounds=art["temp_bounds"])
    else:
        art = _get_artifacts(circuit_key)
        engine = RaceEngine(art["model"], art["encoders"], FEATURE_COLS,
                            track_encoded=0, sim_year=year, temp_bounds=art["temp_bounds"])

    sim = engine.simulate(race["laps"], race["results"])

    # ---- lap time: predicted vs actual ----
    predicted = sim[sim["Driver"] == driver][["Lap", "LapTime", "Position"]].rename(
        columns={"Lap": "LapNumber", "LapTime": "PredictedLapTime", "Position": "PredictedPosition"})
    actual_laps = race["laps"][race["laps"]["Driver"] == driver].copy()
    actual_laps["ActualLapTime"] = actual_laps["LapTime"].dt.total_seconds()
    actual = actual_laps[["LapNumber", "ActualLapTime", "Position"]].rename(
        columns={"Position": "ActualPosition"})

    # ---- gap to leader: predicted vs actual (needs every driver's cumulative time) ----
    sim_leader = sim.groupby("Lap")["CumulativeTime"].min()
    sim_driver_cumu = sim[sim["Driver"] == driver].set_index("Lap")["CumulativeTime"]
    predicted_gap = (sim_driver_cumu - sim_leader.reindex(sim_driver_cumu.index)).rename("PredictedGap")

    # Use the raw "Time" column (true session clock time when the lap was completed)
    # rather than summing LapTime ourselves — a manual sum is thrown off by Safety
    # Car / VSC laps (artificially long individual lap times that don't correspond
    # to a real gap in elapsed time). "Time" is the actual recorded timestamp, so it
    # stays correct through neutralised periods. Verified against the official
    # classified gap on a real SC-affected race: matched to within 0.01s.
    all_laps = race["laps"].copy()
    all_laps["t"] = all_laps["Time"].dt.total_seconds()
    all_laps = all_laps.dropna(subset=["t", "LapNumber"])
    actual_leader = all_laps.groupby("LapNumber")["t"].min()
    actual_driver_t = all_laps[all_laps["Driver"] == driver].set_index("LapNumber")["t"]
    actual_gap = (actual_driver_t - actual_leader.reindex(actual_driver_t.index)).rename("ActualGap")

    merged = (
        predicted.merge(actual, on="LapNumber", how="outer")
        .merge(predicted_gap.rename_axis("LapNumber").reset_index(), on="LapNumber", how="outer")
        .merge(actual_gap.rename_axis("LapNumber").reset_index(), on="LapNumber", how="outer")
        .sort_values("LapNumber")
    )

    def col(name):
        return [None if pd.isna(v) else float(v) for v in merged[name]]

    return {
        "driver": driver,
        "laps": merged["LapNumber"].astype(int).tolist(),
        "predicted_s": col("PredictedLapTime"),
        "actual_s": col("ActualLapTime"),
        "predicted_position": col("PredictedPosition"),
        "actual_position": col("ActualPosition"),
        "predicted_gap_s": col("PredictedGap"),
        "actual_gap_s": col("ActualGap"),
    }


def estimate_pit_loss(event: str, years: list[int]) -> float:
    """
    Median real time lost to a pit stop (in-lap + out-lap combined, each measured
    against the driver's own clean-lap pace), computed from our own historical data
    rather than assumed. Excludes pit laps outside a sane window (5-60s) so a
    Safety-Car-affected stop doesn't skew the estimate.
    """
    losses = []
    for yr in years:
        laps = load_race(yr, event)["laps"].copy()
        laps["sec"] = laps["LapTime"].dt.total_seconds()
        for driver, g in laps.groupby("Driver"):
            g = g.sort_values("LapNumber")
            normal_pace = g[g["IsAccurate"]]["sec"].median()
            if pd.isna(normal_pace):
                continue
            for _, row in g[g["PitInTime"].notna()].iterrows():
                out_rows = g[g["LapNumber"] == row["LapNumber"] + 1]
                in_time = row["sec"]
                out_time = out_rows["sec"].iloc[0] if not out_rows.empty else None
                if pd.notna(in_time) and out_time is not None and pd.notna(out_time):
                    loss = (in_time - normal_pace) + (out_time - normal_pace)
                    if 5 < loss < 60:
                        losses.append(loss)
    return float(pd.Series(losses).median()) if losses else 23.0


def get_pit_recommendation(circuit_key: str, year: int, driver: str) -> dict | None:
    """
    A tyre-degradation-only pit window, derived from the trained lap-time model's own
    learned degradation curve — NOT a predictor of real strategic decisions (undercut
    timing, Safety Cars, traffic are all outside what this model can know). It answers
    one narrower, honest question: "holding everything else fixed, at what tyre age
    has staying out cost more time than a pit stop would?"

    Method: predict lap time at increasing tyre age on the driver's actual first-stint
    compound (other features held at realistic values for that point in the race).
    The cumulative time lost vs a fresh tyre crosses the empirically-measured pit-loss
    at some age — that's the recommended lap. Compared against the real pit lap so you
    can see whether the actual strategy pitted earlier (undercut) or later (overcut)
    than pure tyre physics would suggest.
    """
    from src.features.build_features import COMPOUND_ORDER
    from src.frontend.circuit_profile import get_strategy

    circuit_key = circuit_key.lower()
    if circuit_key not in CIRCUITS:
        raise KeyError(f"Unknown circuit '{circuit_key}'. Available: {list(CIRCUITS)}")
    circ = CIRCUITS[circuit_key]

    strat = get_strategy(circ["event"], year)
    driver_stints = strat[strat["driver"] == driver].sort_values("start_lap")
    if driver_stints.empty:
        return None
    first = driver_stints.iloc[0]
    compound, start_lap, actual_pit_lap = first["compound"], int(first["start_lap"]), int(first["end_lap"])

    race = load_race(year, circ["event"])
    total_laps = int(race["laps"]["LapNumber"].max())
    grid_pos = pd.to_numeric(
        race["results"].set_index("Abbreviation").loc[driver, "GridPosition"], errors="coerce")

    if circuit_key in USE_COMBINED_RACE:
        art = _get_combined_race()
        model, encoders, track_enc = art["model"], art["encoders"], art["track_enc"][circ["label"]]
        bounds = art["temp_bounds"]
    else:
        art = _get_artifacts(circuit_key)
        model, encoders, track_enc = art["model"], art["encoders"], 0
        bounds = art["temp_bounds"]

    driver_enc = int(encoders["Driver"].transform([driver])[0])
    team = race["laps"][race["laps"]["Driver"] == driver]["Team"].iloc[0]
    team_enc = int(encoders["Team"].transform([team])[0])
    compound_enc = COMPOUND_ORDER.get(compound, 1)
    year_encoded = float(year - 2022)
    tt = bounds.get("TrackTemp")
    at = bounds.get("AirTemp")
    track_temp = sum(tt) / 2 if tt else float("nan")
    air_temp = sum(at) / 2 if at else float("nan")

    ages = list(range(1, 36))
    predicted = []
    for age in ages:
        lap_number = start_lap + age - 1
        if lap_number > total_laps:
            break
        fuel_load = 105.0 - (lap_number - 1) * (105.0 / total_laps)
        features = {
            "DriverEncoded": float(driver_enc), "TeamEncoded": float(team_enc),
            "TrackEncoded": float(track_enc), "YearEncoded": year_encoded,
            "LapNumber": float(lap_number), "CompoundEncoded": float(compound_enc),
            "TyreLife": float(age), "TyreLifeSquared": float(age ** 2),
            "FuelLoad": fuel_load, "GridPosition": float(grid_pos) if pd.notna(grid_pos) else 10.0,
            "TrackTemp": track_temp, "AirTemp": air_temp,
        }
        X = pd.DataFrame([features])[FEATURE_COLS]
        predicted.append(float(model.predict(X)[0]))

    pit_loss = estimate_pit_loss(circ["event"], TRAIN_YEARS)
    fresh = predicted[0]
    cumulative_loss = 0.0
    recommended_age = None
    for i, p in enumerate(predicted):
        cumulative_loss += (p - fresh)
        if cumulative_loss >= pit_loss:
            recommended_age = ages[i]
            break

    return {
        "driver": driver, "compound": compound, "start_lap": start_lap,
        "actual_pit_lap": actual_pit_lap,
        "recommended_pit_lap": start_lap + recommended_age - 1 if recommended_age else None,
        "pit_loss_s": round(pit_loss, 2),
        "degradation_curve": {"tyre_age": ages[:len(predicted)], "predicted_lap_s": predicted},
    }


def _get_combined_qual() -> dict:
    """Load (and cache) the pooled qualifying model, reusing the shared pool artifacts."""
    if _combined_qual_cache:
        return _combined_qual_cache
    pool = _get_pool_artifacts()
    _combined_qual_cache.update({
        "encoders": pool["encoders"],
        "model": load_model(COMBINED_QUAL_MODEL),
        "track_enc": pool["track_enc"],
    })
    return _combined_qual_cache


def predict_qualifying_for(circuit_key: str, year: int, use_cache: bool = True) -> dict:
    """
    Predict a circuit's qualifying grid. Hybrid model choice: the pooled model for
    data-thin circuits (USE_COMBINED_QUAL), each circuit's specialized model otherwise.
    """
    circuit_key = circuit_key.lower()
    if circuit_key not in CIRCUITS:
        raise KeyError(f"Unknown circuit '{circuit_key}'. Available: {list(CIRCUITS)}")
    if year not in SERVE_YEARS:
        raise ValueError(f"Year {year} not servable. Available: {SERVE_YEARS}")

    ck = ("qual", circuit_key, year)
    if use_cache and ck in _result_cache:
        return _result_cache[ck]

    circ = CIRCUITS[circuit_key]
    best = extract_best_qualifying_laps(load_qualifying(year, circ["event"])["laps"])
    race_results = load_race(year, circ["event"])["results"]

    if circuit_key in USE_COMBINED_QUAL:
        art = _get_combined_qual()
        pred = predict_qualifying(best, race_results, art["model"], art["encoders"],
                                  FEATURE_COLS, art["track_enc"][circ["label"]], year=year)
        model_name, approach = COMBINED_QUAL_MODEL, "pooled (thin specialized data)"
    else:
        art = _get_artifacts(circuit_key)
        pred = predict_qualifying(best, race_results, art["qual_model"], art["encoders"],
                                  FEATURE_COLS, 0, year=year)
        model_name, approach = circ["model"].replace("laptime_", "qualtime_"), "specialized"

    pred = pred.sort_values("PredPos")
    results = [{
        "pred_grid":        int(r["PredPos"]),
        "driver":           r["Driver"],
        "team":             r["Team"],
        "predicted_time_s": round(float(r["PredictedTime"]), 3),
        "actual_time_s":    round(float(r["ActualTime"]), 3),
        "actual_grid":      int(r["ActualPos"]),
        "grid_error":       int(r["PosDelta"]),
    } for _, r in pred.iterrows()]
    metrics = {
        "lap_time_rmse_s":    round(float((pred["Delta"] ** 2).mean() ** 0.5), 3),
        "mean_grid_error":    round(float(pred["PosDelta"].mean()), 3),
        "within_2_positions": int((pred["PosDelta"] <= 2).sum()),
        "exact_positions":    int((pred["PosDelta"] == 0).sum()),
        "drivers":            int(len(pred)),
    }
    resp = {"circuit": circ["label"], "year": year, "model": model_name,
            "approach": approach, "metrics": metrics, "results": results}
    _result_cache[ck] = resp
    return resp
