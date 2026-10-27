"""
Single-circuit and multi-circuit analysis pipeline.

run_circuit()       — one circuit, one or multiple training years
run_multi_circuit() — several circuits, combined model
"""

import pandas as pd
from src.ingestion.load_session import load_race, load_qualifying
from src.features.build_features import (
    build_encoders,
    build_feature_frame,
    build_qualifying_feature_frame,
    temp_bounds,
    FEATURE_COLS,
    TARGET_COL,
)
from src.model.train import train, save_model
from src.engine.race_engine import RaceEngine
from src.analytics.compare import print_summary
from src.analytics.qualifying import (
    extract_best_qualifying_laps,
    predict_qualifying,
    print_qualifying_report,
)


def run_circuit(
    event,
    track_label: str,
    train_years: list[int],
    test_year: int,
    encoders: dict = None,
    track_encoded: int = 0,
) -> dict:
    """
    Full analysis pipeline for one circuit.

    event        : FastF1 identifier — round number (int) or event name (str)
    track_label  : short label used in feature encoding, e.g. "Bahrain", "Spa"
    train_years  : list of years to train on, e.g. [2022, 2023, 2024]
    test_year    : year to simulate and compare against actual results
    encoders     : pre-built encoders (pass in for multi-circuit shared encoders)
    track_encoded: integer index for this track in the Track LabelEncoder
    """
    print(f"\n{'='*60}")
    print(f"  {track_label.upper()}")
    print(f"  Train: {train_years}  ->  Test: {test_year}")
    print(f"{'='*60}")

    # ── Load all sessions ─────────────────────────────────────────────────────
    races_train = {}
    quals_train = {}
    for yr in train_years:
        print(f"  Loading {yr} race...")
        races_train[yr] = load_race(yr, event)
        print(f"  Loading {yr} qualifying...")
        quals_train[yr] = load_qualifying(yr, event)

    print(f"  Loading {test_year} race...")
    race_test = load_race(test_year, event)

    print(f"  Loading {test_year} qualifying...")
    qual_test = load_qualifying(test_year, event)

    # ── Build encoders across ALL sessions (race + qualifying, all years) ──────
    if encoders is None:
        all_sessions = (
            [{"laps": races_train[yr]["laps"], "track_name": track_label} for yr in train_years]
            + [{"laps": quals_train[yr]["laps"], "track_name": track_label} for yr in train_years]
            + [
                {"laps": race_test["laps"], "track_name": track_label},
                {"laps": qual_test["laps"],  "track_name": track_label},
            ]
        )
        print(f"  Building encoders from {train_years + [test_year]} rosters...")
        encoders = build_encoders(all_sessions)

    # ── Build race feature frames ──────────────────────────────────────────────
    print("\n  Building race feature frames...")
    train_frames = [
        build_feature_frame(races_train[yr]["laps"], races_train[yr]["results"], track_label, encoders, yr)
        for yr in train_years
    ]
    combined_train = pd.concat(train_frames, ignore_index=True)
    print(f"  Combined race training set: {len(combined_train):,} laps ({', '.join(str(y) for y in train_years)})")
    race_bounds = temp_bounds(combined_train)   # clip inference temps to this range

    # ── Train race model ───────────────────────────────────────────────────────
    year_str = "_".join(str(y) for y in train_years)
    print(f"\n  Training race model on {track_label} {year_str} data...")
    model = train(combined_train, FEATURE_COLS, TARGET_COL)
    save_model(model, f"laptime_{track_label.lower()}_{year_str}")

    # ── Build qualifying feature frames and train qualifying model ─────────────
    print(f"\n  Building qualifying feature frames...")
    qual_train_frames = [
        build_qualifying_feature_frame(
            quals_train[yr]["laps"], quals_train[yr]["results"], track_label, encoders, yr
        )
        for yr in train_years
    ]
    combined_qual_train = pd.concat(qual_train_frames, ignore_index=True)
    print(f"  Combined qualifying training set: {len(combined_qual_train):,} laps")
    qual_bounds = temp_bounds(combined_qual_train)

    print(f"\n  Training qualifying model on {track_label} {year_str} data...")
    qual_model = train(combined_qual_train, FEATURE_COLS, TARGET_COL)
    save_model(qual_model, f"qualtime_{track_label.lower()}_{year_str}")

    # ── Simulate each training year (in-sample sanity check) ──────────────────
    for yr in train_years:
        engine = RaceEngine(model, encoders, FEATURE_COLS, track_encoded=track_encoded, sim_year=yr)
        print(f"\n  [IN-SAMPLE {yr}] Simulating {track_label}...")
        sim = engine.simulate(races_train[yr]["laps"], races_train[yr]["results"])
        print_summary(sim, races_train[yr]["results"], races_train[yr]["laps"])

    # ── Simulate test year (out-of-sample — the real test) ────────────────────
    engine_test = RaceEngine(model, encoders, FEATURE_COLS, track_encoded=track_encoded, sim_year=test_year, temp_bounds=race_bounds)
    print(f"\n  [OUT-OF-SAMPLE {test_year}] Simulating {track_label}...")
    sim_test = engine_test.simulate(race_test["laps"], race_test["results"])
    print_summary(sim_test, race_test["results"], race_test["laps"])

    # ── Qualifying prediction (uses dedicated qualifying model) ────────────────
    print(f"\n  Qualifying prediction for {test_year} {track_label}...")
    best_qual = extract_best_qualifying_laps(qual_test["laps"])
    qual_pred = predict_qualifying(
        best_qual, race_test["results"], qual_model, encoders, FEATURE_COLS,
        track_encoded, year=test_year, temp_bounds=qual_bounds,
    )
    print_qualifying_report(qual_pred)

    return {
        "model":      model,
        "qual_model": qual_model,
        "encoders":   encoders,
        "sim_test":   sim_test,
        "qual_pred":  qual_pred,
        "race_test":  race_test,
    }


def run_multi_circuit(
    circuits: list[dict],
    train_years: list[int],
    test_year: int,
) -> None:
    """
    Train ONE race model + ONE qualifying model across multiple circuits combined, then test on each.

    circuits: [{"event": ..., "track_label": str}, ...]
    """
    print(f"\n{'='*60}")
    print(f"  MULTI-CIRCUIT MODEL")
    print(f"  Circuits : {[c['track_label'] for c in circuits]}")
    print(f"  Train    : {train_years}  ->  Test: {test_year}")
    print(f"{'='*60}")

    # ── Load all sessions ─────────────────────────────────────────────────────
    sessions: dict[str, dict] = {}
    for c in circuits:
        label = c["track_label"]
        sessions[label] = {"train": {}, "qual_train": {}, "test": None, "qual": None}
        for yr in train_years:
            print(f"  Loading {label} {yr} race...")
            sessions[label]["train"][yr] = load_race(yr, c["event"])
            print(f"  Loading {label} {yr} qualifying...")
            sessions[label]["qual_train"][yr] = load_qualifying(yr, c["event"])
        print(f"  Loading {label} {test_year} race...")
        sessions[label]["test"] = load_race(test_year, c["event"])
        print(f"  Loading {label} {test_year} qualifying...")
        sessions[label]["qual"] = load_qualifying(test_year, c["event"])

    # ── Shared encoders across all sessions ───────────────────────────────────
    print("\n  Building shared encoders...")
    encoder_inputs = []
    for c in circuits:
        label = c["track_label"]
        for yr in train_years:
            encoder_inputs.append({"laps": sessions[label]["train"][yr]["laps"], "track_name": label})
            encoder_inputs.append({"laps": sessions[label]["qual_train"][yr]["laps"], "track_name": label})
        encoder_inputs.append({"laps": sessions[label]["test"]["laps"], "track_name": label})
        encoder_inputs.append({"laps": sessions[label]["qual"]["laps"],  "track_name": label})

    encoders = build_encoders(encoder_inputs)
    track_enc_map = {
        lbl: int(encoders["Track"].transform([lbl])[0])
        for lbl in encoders["Track"].classes_
    }
    print(f"  Track encodings: {track_enc_map}")

    # ── Build combined race training set ──────────────────────────────────────
    print("\n  Building race feature frames...")
    all_train_frames = []
    for c in circuits:
        label = c["track_label"]
        for yr in train_years:
            df = build_feature_frame(
                sessions[label]["train"][yr]["laps"],
                sessions[label]["train"][yr]["results"],
                label, encoders, yr,
            )
            all_train_frames.append(df)

    combined_train = pd.concat(all_train_frames, ignore_index=True)
    n_circuit_years = len(circuits) * len(train_years)
    print(f"  Combined race: {len(combined_train):,} laps across {n_circuit_years} circuit-years")

    # ── Build combined qualifying training set ────────────────────────────────
    print("\n  Building qualifying feature frames...")
    all_qual_frames = []
    for c in circuits:
        label = c["track_label"]
        for yr in train_years:
            df = build_qualifying_feature_frame(
                sessions[label]["qual_train"][yr]["laps"],
                sessions[label]["qual_train"][yr]["results"],
                label, encoders, yr,
            )
            all_qual_frames.append(df)

    combined_qual_train = pd.concat(all_qual_frames, ignore_index=True)
    print(f"  Combined qualifying: {len(combined_qual_train):,} laps across {n_circuit_years} circuit-years")

    # ── Train combined race model ──────────────────────────────────────────────
    track_str = "_".join(c["track_label"].lower() for c in circuits)
    year_str  = "_".join(str(y) for y in train_years)
    print(f"\n  Training combined race model ({len(combined_train):,} laps)...")
    model = train(combined_train, FEATURE_COLS, TARGET_COL)
    save_model(model, f"laptime_multi_{track_str}_{year_str}")

    # ── Train combined qualifying model ───────────────────────────────────────
    print(f"\n  Training combined qualifying model ({len(combined_qual_train):,} laps)...")
    qual_model = train(combined_qual_train, FEATURE_COLS, TARGET_COL)
    save_model(qual_model, f"qualtime_multi_{track_str}_{year_str}")

    # ── Per-circuit simulation and reporting ──────────────────────────────────
    for c in circuits:
        label = c["track_label"]
        t_enc = track_enc_map[label]

        for yr in train_years:
            engine = RaceEngine(model, encoders, FEATURE_COLS, track_encoded=t_enc, sim_year=yr)
            print(f"\n  [{label} IN-SAMPLE {yr}]")
            sim = engine.simulate(sessions[label]["train"][yr]["laps"], sessions[label]["train"][yr]["results"])
            print_summary(sim, sessions[label]["train"][yr]["results"], sessions[label]["train"][yr]["laps"])

        engine_test = RaceEngine(model, encoders, FEATURE_COLS, track_encoded=t_enc, sim_year=test_year)
        print(f"\n  [{label} OUT-OF-SAMPLE {test_year}]")
        sim_test = engine_test.simulate(sessions[label]["test"]["laps"], sessions[label]["test"]["results"])
        print_summary(sim_test, sessions[label]["test"]["results"], sessions[label]["test"]["laps"])

        print(f"\n  [{label}] Qualifying {test_year}...")
        best_qual = extract_best_qualifying_laps(sessions[label]["qual"]["laps"])
        qual_pred = predict_qualifying(
            best_qual, sessions[label]["test"]["results"],
            qual_model, encoders, FEATURE_COLS, t_enc, year=test_year,
        )
        print_qualifying_report(qual_pred)
