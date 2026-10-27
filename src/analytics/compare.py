import pandas as pd
import numpy as np


def final_classification(sim_df: pd.DataFrame) -> pd.DataFrame:
    """Extract simulated finishing positions from the last lap of the simulation."""
    last_lap = sim_df["Lap"].max()
    return (
        sim_df[sim_df["Lap"] == last_lap]
        [["Position", "Driver", "Team", "CumulativeTime"]]
        .sort_values("Position")
        .reset_index(drop=True)
    )


def compare_positions(sim_df: pd.DataFrame, actual_results: pd.DataFrame) -> pd.DataFrame:
    """
    Side-by-side table of simulated vs actual finishing positions.
    PositionError = |SimPosition - ActualPosition|.
    """
    sim_final = (
        final_classification(sim_df)
        [["Driver", "Position"]]
        .rename(columns={"Position": "SimPos"})
    )

    actual = (
        actual_results[["Abbreviation", "Position"]]
        .rename(columns={"Abbreviation": "Driver", "Position": "ActualPos"})
        .copy()
    )
    actual["ActualPos"] = pd.to_numeric(actual["ActualPos"], errors="coerce")

    merged = sim_final.merge(actual, on="Driver").dropna()
    merged["Error"] = (merged["SimPos"] - merged["ActualPos"]).abs().astype(int)
    return merged.sort_values("ActualPos").reset_index(drop=True)


def lap_time_rmse(sim_df: pd.DataFrame, raw_laps: pd.DataFrame) -> pd.DataFrame:
    """
    Per-driver RMSE between simulated lap times and actual FastF1 lap times.
    Only compares laps where FastF1 has IsAccurate=True (same filter as training).
    """
    actual_clean = raw_laps[raw_laps["IsAccurate"]].copy()
    actual_clean["ActualLapTime"] = actual_clean["LapTime"].dt.total_seconds()
    actual_clean = actual_clean[["Driver", "LapNumber", "ActualLapTime"]].dropna()

    sim_clean = sim_df[["Driver", "Lap", "LapTime"]].rename(
        columns={"Lap": "LapNumber", "LapTime": "SimLapTime"}
    )

    merged = actual_clean.merge(sim_clean, on=["Driver", "LapNumber"])
    merged["ResidualSq"] = (merged["SimLapTime"] - merged["ActualLapTime"]) ** 2

    per_driver = (
        merged.groupby("Driver")["ResidualSq"]
        .agg(["mean", "count"])
        .rename(columns={"mean": "MSE", "count": "Laps"})
    )
    per_driver["RMSE"] = np.sqrt(per_driver["MSE"]).round(3)
    return per_driver[["RMSE", "Laps"]].sort_values("RMSE")


def gap_evolution(sim_df: pd.DataFrame, driver_a: str, driver_b: str) -> pd.DataFrame:
    """Time gap between two drivers across every lap of the race (positive = A leads)."""
    a = sim_df[sim_df["Driver"] == driver_a][["Lap", "CumulativeTime"]].set_index("Lap")
    b = sim_df[sim_df["Driver"] == driver_b][["Lap", "CumulativeTime"]].set_index("Lap")
    gap = (b["CumulativeTime"] - a["CumulativeTime"]).rename("Gap")
    return gap.reset_index()


def print_summary(sim_df: pd.DataFrame, actual_results: pd.DataFrame, raw_laps: pd.DataFrame) -> None:
    print("\n" + "=" * 55)
    print("  SIMULATED vs ACTUAL — FINAL CLASSIFICATION")
    print("=" * 55)

    comparison = compare_positions(sim_df, actual_results)
    exact = (comparison["Error"] == 0).sum()
    within_2 = (comparison["Error"] <= 2).sum()
    mae = comparison["Error"].mean()

    for _, row in comparison.iterrows():
        marker = "<--" if row["Error"] == 0 else f"  ({row['Error']:+d})" if row["Error"] > 0 else f"  ({row['Error']})"
        print(f"  P{int(row['ActualPos']):2d}  {row['Driver']}  |  sim: P{int(row['SimPos']):2d}  {marker}")

    print(f"\n  Exact positions correct : {exact}/20")
    print(f"  Within 2 positions      : {within_2}/20")
    print(f"  Mean position error     : {mae:.2f} places")

    print("\n" + "=" * 55)
    print("  PER-DRIVER LAP TIME RMSE  (model vs actual clean laps)")
    print("=" * 55)
    rmse_df = lap_time_rmse(sim_df, raw_laps)
    for driver, row in rmse_df.iterrows():
        bar = "#" * int(row["RMSE"] * 10)
        print(f"  {driver:<4}  {row['RMSE']:.3f}s  {bar}  ({int(row['Laps'])} laps)")
    print(f"\n  Fleet RMSE: {np.sqrt((rmse_df['RMSE']**2).mean()):.3f}s")
