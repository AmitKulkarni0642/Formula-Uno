import pandas as pd
import numpy as np
from src.features.build_features import clip_temp


def extract_best_qualifying_laps(qual_laps: pd.DataFrame) -> pd.DataFrame:
    """
    For each driver, find the single fastest accurate lap from qualifying.
    This is the lap the model will try to predict.

    Qualifying laps use IsAccurate=True same as race — removes out-laps,
    in-laps, and any lap where timing was interrupted.
    """
    clean = qual_laps[
        qual_laps["IsAccurate"]
        & qual_laps["LapTime"].notna()
        & qual_laps["Compound"].notna()
        & qual_laps["Compound"].ne("UNKNOWN")
        & qual_laps["TyreLife"].notna()
    ].copy()

    clean["LapTimeSeconds"] = clean["LapTime"].dt.total_seconds()

    # Keep only the fastest lap per driver — that's what sets their grid position
    best = (
        clean.sort_values("LapTimeSeconds")
        .groupby("Driver", as_index=False)
        .first()
    )

    cols = ["Driver", "Team", "LapNumber", "Compound", "TyreLife", "LapTimeSeconds", "TrackTemp", "AirTemp"]
    return best[[c for c in cols if c in best.columns]].copy()


def predict_qualifying(
    best_laps: pd.DataFrame,
    race_results: pd.DataFrame,
    model,
    encoders: dict,
    feature_cols: list,
    track_encoded: int = 0,
    year: int = 2023,
    reg_era_start: int = 2022,
    temp_bounds: dict = None,
) -> pd.DataFrame:
    """
    Run the race-trained model on each driver's best qualifying lap features.

    We use the actual qualifying lap features (compound, tyre age, lap number)
    rather than hypothetical values — this tests whether the race model
    generalises to single-lap qualifying pace.

    GridPosition is filled from the race results as a proxy for car/driver quality.
    In qualifying there is no grid position yet, but the race model expects this
    feature. Using the final race grid position is the closest available proxy.
    """
    COMPOUND_ORDER = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTERMEDIATE": 3, "WET": 4}
    temp_bounds = temp_bounds or {}

    driver_encoder = encoders["Driver"]
    team_encoder = encoders["Team"]

    grid = race_results[["Abbreviation", "GridPosition"]].copy()
    grid["GridPosition"] = pd.to_numeric(grid["GridPosition"], errors="coerce")
    grid_map = dict(zip(grid["Abbreviation"], grid["GridPosition"]))

    rows = []
    for _, lap in best_laps.iterrows():
        driver = lap["Driver"]
        team = lap["Team"]

        try:
            driver_enc = int(driver_encoder.transform([driver])[0])
            team_enc = int(team_encoder.transform([team])[0])
        except ValueError:
            continue  # driver not seen in race training data

        compound_enc = COMPOUND_ORDER.get(lap["Compound"], 0)
        grid_pos = grid_map.get(driver, 10.0)

        tyre_life = float(lap["TyreLife"])
        features = {
            "DriverEncoded":   float(driver_enc),
            "TeamEncoded":     float(team_enc),
            "TrackEncoded":    float(track_encoded),
            "YearEncoded":     float(year - reg_era_start),
            "LapNumber":       float(lap["LapNumber"]),
            "CompoundEncoded": float(compound_enc),
            "TyreLife":        tyre_life,
            "TyreLifeSquared": tyre_life ** 2,
            "FuelLoad":        5.0,   # qualifying cars run minimal fuel
            "GridPosition":    float(grid_pos),
            "TrackTemp":       clip_temp(float(lap["TrackTemp"]) if "TrackTemp" in lap else float("nan"), temp_bounds.get("TrackTemp")),
            "AirTemp":         clip_temp(float(lap["AirTemp"]) if "AirTemp" in lap else float("nan"), temp_bounds.get("AirTemp")),
        }

        X = pd.DataFrame([features])[feature_cols]
        predicted = float(model.predict(X)[0])

        rows.append({
            "Driver": driver,
            "Team": team,
            "ActualTime": round(lap["LapTimeSeconds"], 3),
            "PredictedTime": round(predicted, 3),
            "Delta": round(predicted - lap["LapTimeSeconds"], 3),
            "Compound": lap["Compound"],
            "TyreLife": int(lap["TyreLife"]),
        })

    df = pd.DataFrame(rows)

    # Rank by predicted time → predicted grid
    df["PredPos"] = df["PredictedTime"].rank(method="min").astype(int)
    # Rank by actual time → actual qualifying position
    df["ActualPos"] = df["ActualTime"].rank(method="min").astype(int)
    df["PosDelta"] = (df["PredPos"] - df["ActualPos"]).abs()

    return df.sort_values("ActualPos").reset_index(drop=True)


def print_qualifying_report(df: pd.DataFrame) -> None:
    exact = (df["PosDelta"] == 0).sum()
    within_2 = (df["PosDelta"] <= 2).sum()
    mae = df["PosDelta"].mean()
    time_rmse = np.sqrt((df["Delta"] ** 2).mean())

    print("\n" + "=" * 65)
    print("  QUALIFYING PREDICTION — Dedicated Qualifying Model")
    print("=" * 65)
    print(f"  {'ActPos':<7} {'Driver':<6} {'Actual':>9} {'Predicted':>10} {'Delta':>8} {'PredPos':>8}")
    print("  " + "-" * 55)

    for _, row in df.iterrows():
        marker = "<--" if row["PosDelta"] == 0 else f"({row['PredPos']:+.0f})".replace("+", "P").replace("-", "P")
        sign = "+" if row["Delta"] >= 0 else ""
        print(
            f"  P{int(row['ActualPos']):<6} {row['Driver']:<6} "
            f"{row['ActualTime']:>9.3f}s  {row['PredictedTime']:>9.3f}s  "
            f"{sign}{row['Delta']:>6.3f}s  -> P{int(row['PredPos'])}"
        )

    print(f"\n  Exact grid positions correct : {exact}/{len(df)}")
    print(f"  Within 2 positions           : {within_2}/{len(df)}")
    print(f"  Mean position error          : {mae:.2f} places")
    print(f"  Lap time RMSE                : {time_rmse:.3f}s")
    print()
    print("  Model: dedicated qualifying model trained on historical qualifying laps.")
