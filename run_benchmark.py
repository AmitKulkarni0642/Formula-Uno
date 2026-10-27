"""
Compare candidate models on one circuit's race data (default: Bahrain, 2022-2024).

Run:  python run_benchmark.py
"""

import pandas as pd
from src.ingestion.load_session import load_race
from src.features.build_features import build_encoders, build_feature_frame, FEATURE_COLS, TARGET_COL
from src.model.benchmark import benchmark_models, print_benchmark

EVENT, LABEL, YEARS = "Bahrain Grand Prix", "Bahrain", [2022, 2023, 2024]

races = {yr: load_race(yr, EVENT) for yr in YEARS}
encoders = build_encoders([{"laps": races[yr]["laps"], "track_name": LABEL} for yr in YEARS])
df = pd.concat(
    [build_feature_frame(races[yr]["laps"], races[yr]["results"], LABEL, encoders, yr) for yr in YEARS],
    ignore_index=True,
)

res = benchmark_models(df, FEATURE_COLS, TARGET_COL)
print_benchmark(res, f"{LABEL} race — {len(df):,} laps across {len(YEARS)} seasons")
