"""
Formula Uno — single entry point for running everything from the terminal.

Works from ANY directory (it moves to the project root itself). Examples:

    python run.py list
    python run.py train bahrain
    python run.py train-all
    python run.py predict bahrain 2025
    python run.py benchmark
    python run.py api
"""

import os
import sys

# Make the project runnable no matter where it's launched from.
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))  # F1_USERNAME / F1_PASSWORD, for fuller FastF1 telemetry access

import argparse

CIRCUITS = {
    "bahrain":   ("Bahrain Grand Prix", "Bahrain"),
    "spa":       ("Belgian Grand Prix", "Spa"),
    "austria":   ("Austrian Grand Prix", "Austria"),
    "australia": ("Australian Grand Prix", "Australia"),
    "monza":     ("Italian Grand Prix", "Monza"),
    "abudhabi":  ("Abu Dhabi Grand Prix", "AbuDhabi"),
    "mexico":    ("Mexico City Grand Prix", "Mexico"),
    "monaco":    ("Monaco Grand Prix", "Monaco"),
    "canada":    ("Canadian Grand Prix", "Canada"),
    "silverstone": ("British Grand Prix", "Silverstone"),
}
TRAIN_YEARS = [2022, 2023, 2024]


def _check_circuit(c: str) -> None:
    if c not in CIRCUITS:
        print(f"Unknown circuit '{c}'. Choose from: {', '.join(CIRCUITS)}")
        sys.exit(1)


def cmd_list(args) -> None:
    print("\nCircuits you can train / predict:")
    for k, (ev, _) in CIRCUITS.items():
        print(f"  {k:<9}  ->  {ev}")
    print("\nYears: models train on 2022-2024; predict any of 2022-2025 (2025 = out-of-sample).")
    print("\nExamples:")
    print("  python run.py train-all              # train every circuit")
    print("  python run.py predict bahrain 2025   # see a prediction in the terminal")
    print("  python run.py benchmark              # compare models")
    print("  python run.py api                    # start the web API\n")


def _train_one(circuit: str) -> None:
    from src.pipeline import run_circuit
    ev, lbl = CIRCUITS[circuit]
    run_circuit(event=ev, track_label=lbl, train_years=TRAIN_YEARS, test_year=2025)


def cmd_train(args) -> None:
    _check_circuit(args.circuit)
    _train_one(args.circuit)


def cmd_train_all(args) -> None:
    for c in CIRCUITS:
        print(f"\n########## TRAINING {c.upper()} ##########")
        _train_one(c)


def cmd_predict(args) -> None:
    _check_circuit(args.circuit)
    from src.api.predict_service import predict_race
    try:
        r = predict_race(args.circuit, args.year)
    except FileNotFoundError:
        print(f"\nNo trained model for '{args.circuit}' yet. Run:  python run.py train {args.circuit}\n")
        sys.exit(1)

    m = r["metrics"]
    tag = "in-sample" if r["in_sample"] else "OUT-OF-SAMPLE"
    print("\n" + "=" * 58)
    print(f"  {r['circuit'].upper()} {r['year']}  -  predicted finishing order  [{tag}]")
    print("=" * 58)
    print(f"  {'Sim':<5}{'Drv':<5}{'Team':<16}{'Actual':<8}{'Err':>3}")
    print("  " + "-" * 52)
    for row in r["results"]:
        print(f"  P{row['sim_position']:<4}{row['driver']:<5}{str(row['team'])[:15]:<16}"
              f"P{row['actual_position']:<7}{row['position_error']:>3}")
    print("  " + "-" * 52)
    print(f"  Mean position error : {m['mean_position_error']} places")
    print(f"  Within 2 positions  : {m['within_2_positions']}/{m['drivers_compared']}")
    print(f"  Fleet lap-time RMSE : {m['fleet_lap_rmse_s']}s\n")


def cmd_benchmark(args) -> None:
    _check_circuit(args.circuit)
    import pandas as pd
    from src.ingestion.load_session import load_race
    from src.features.build_features import build_encoders, build_feature_frame, FEATURE_COLS, TARGET_COL
    from src.model.benchmark import benchmark_models, print_benchmark
    ev, lbl = CIRCUITS[args.circuit]
    races = {yr: load_race(yr, ev) for yr in TRAIN_YEARS}
    encoders = build_encoders([{"laps": races[yr]["laps"], "track_name": lbl} for yr in TRAIN_YEARS])
    df = pd.concat(
        [build_feature_frame(races[yr]["laps"], races[yr]["results"], lbl, encoders, yr) for yr in TRAIN_YEARS],
        ignore_index=True,
    )
    res = benchmark_models(df, FEATURE_COLS, TARGET_COL)
    print_benchmark(res, f"{lbl} race — {len(df):,} laps")


def cmd_devrace(args) -> None:
    from src.analytics.development import season_gap_to_pole, best_single_changepoint
    print(f"\nPulling {args.year} qualifying results for {args.team} (first run downloads a full season)...")
    df = season_gap_to_pole(args.year, args.team)
    if df.empty:
        print(f"No dry qualifying pace found for {args.team} in {args.year}.")
        return

    print(f"\n{args.team} {args.year}  -  qualifying gap to pole, race by race")
    print(f"  {'Rnd':>3}  {'Event':<32}{'Gap':>9}")
    print("  " + "-" * 46)
    for _, r in df.iterrows():
        print(f"  {int(r['round']):>3}  {r['event'][:32]:<32}{r['gap_s']:>+8.3f}s")
    print("  " + "-" * 46)

    i, frac = best_single_changepoint(df["gap_s"].values)
    if i is None:
        print("  No clear step-change detected in the season.\n")
        return
    before = df["gap_s"].iloc[:i].mean()
    after = df["gap_s"].iloc[i:].mean()
    ev = df["event"].iloc[i]
    rnd = int(df["round"].iloc[i])
    print(f"  STEP-CHANGE detected before round {rnd} ({ev}):")
    print(f"    mean gap before : {before:>+7.3f}s")
    print(f"    mean gap after  : {after:>+7.3f}s")
    print(f"    improvement     : {before - after:>7.3f}s  (explains {frac * 100:.0f}% of the season's variance)\n")


def cmd_api(args) -> None:
    import uvicorn
    print("\nStarting API at http://127.0.0.1:8000")
    print("Open http://127.0.0.1:8000/docs in your browser. Press Ctrl+C to stop.\n")
    uvicorn.run("src.api.app:app", host="127.0.0.1", port=8000, reload=False)


def cmd_frontend(args) -> None:
    import subprocess
    app_path = os.path.join(ROOT, "src", "frontend", "streamlit_app.py")
    print("\nStarting the Formula Uno frontend (Ctrl+C to stop)...\n")
    subprocess.run([sys.executable, "-m", "streamlit", "run", app_path])


def main() -> None:
    p = argparse.ArgumentParser(prog="run.py", description="Formula Uno runner")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show circuits and example commands").set_defaults(func=cmd_list)

    tp = sub.add_parser("train", help="train + evaluate one circuit")
    tp.add_argument("circuit", help="bahrain | spa | austria")
    tp.set_defaults(func=cmd_train)

    sub.add_parser("train-all", help="train + evaluate every circuit").set_defaults(func=cmd_train_all)

    pp = sub.add_parser("predict", help="print a predicted finishing order to the terminal")
    pp.add_argument("circuit", help="bahrain | spa | austria")
    pp.add_argument("year", type=int, nargs="?", default=2025, help="season (default 2025)")
    pp.set_defaults(func=cmd_predict)

    bp = sub.add_parser("benchmark", help="compare models on a circuit's race data")
    bp.add_argument("circuit", nargs="?", default="bahrain", help="default bahrain")
    bp.set_defaults(func=cmd_benchmark)

    sub.add_parser("api", help="start the web API server").set_defaults(func=cmd_api)
    sub.add_parser("frontend", help="start the Streamlit frontend").set_defaults(func=cmd_frontend)

    dr = sub.add_parser("devrace", help="detect a team's development step-change across a season")
    dr.add_argument("year", type=int, help="season, e.g. 2023")
    dr.add_argument("team", nargs="?", default="McLaren", help="team name (default McLaren)")
    dr.set_defaults(func=cmd_devrace)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
