from src.ingestion.load_session import load_race, load_qualifying
from src.features.build_features import build_encoders, build_feature_frame, FEATURE_COLS, TARGET_COL
from src.model.train import train, save_model
from src.engine.race_engine import RaceEngine
from src.analytics.compare import print_summary
from src.analytics.qualifying import (
    extract_best_qualifying_laps,
    predict_qualifying,
    print_qualifying_report,
)

TRACK = "Bahrain"
ROUND = 1

# ── 1. Load both years ────────────────────────────────────────────────────────
print("Loading 2023 Bahrain race...")
race_2023 = load_race(2023, ROUND)

print("Loading 2024 Bahrain race...")
race_2024 = load_race(2024, ROUND)

print("Loading 2024 Bahrain qualifying...")
qual_2024 = load_qualifying(2024, ROUND)

# ── 2. Fit encoders on the union of both years ────────────────────────────────
# This handles driver changes (De Vries → Ricciardo) and team renames
# (Alfa Romeo → Sauber) without throwing unseen-label errors.
print("\nFitting encoders on 2023 + 2024 roster union...")
encoders = build_encoders([
    {"laps": race_2023["laps"], "track_name": TRACK},
    {"laps": race_2024["laps"], "track_name": TRACK},
])
print(f"  Drivers known: {list(encoders['Driver'].classes_)}")
print(f"  Teams known:   {list(encoders['Team'].classes_)}")

# ── 3. Build feature frames ───────────────────────────────────────────────────
print("\nBuilding feature frames...")
train_df = build_feature_frame(race_2023["laps"], race_2023["results"], TRACK, encoders)
test_df  = build_feature_frame(race_2024["laps"], race_2024["results"], TRACK, encoders)

# ── 4. Train on 2023 only ─────────────────────────────────────────────────────
print("\nTraining model on 2023 Bahrain data...")
model = train(train_df, FEATURE_COLS, TARGET_COL)
save_model(model, f"laptime_{TRACK.lower()}_2023")

# ── 5. Evaluate on 2023 (in-sample sanity check) ─────────────────────────────
print("\n" + "=" * 60)
print("  IN-SAMPLE VALIDATION: Simulate 2023 Bahrain (trained on this race)")
print("=" * 60)
engine = RaceEngine(model, encoders, FEATURE_COLS, track_encoded=0)
sim_2023 = engine.simulate(race_2023["laps"], race_2023["results"])
print_summary(sim_2023, race_2023["results"], race_2023["laps"])

# ── 6. Evaluate on 2024 (out-of-sample — the real test) ──────────────────────
print("\n" + "=" * 60)
print("  OUT-OF-SAMPLE TEST: Simulate 2024 Bahrain (never seen by model)")
print("  Note: model knows 2023 car performance, not 2024 developments")
print("=" * 60)
sim_2024 = engine.simulate(race_2024["laps"], race_2024["results"])
print_summary(sim_2024, race_2024["results"], race_2024["laps"])

# ── 7. Qualifying prediction on 2024 ─────────────────────────────────────────
print("\n--- 2024 Qualifying prediction (race model applied to single laps) ---")
best_qual = extract_best_qualifying_laps(qual_2024["laps"])
qual_pred = predict_qualifying(best_qual, race_2024["results"], model, encoders, FEATURE_COLS)
print_qualifying_report(qual_pred)
