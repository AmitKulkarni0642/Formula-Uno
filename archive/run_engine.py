from src.ingestion.load_session import load_race
from src.features.build_features import build_feature_frame
from src.model.train import train, save_model
from src.engine.race_engine import RaceEngine
from src.analytics.compare import print_summary

# --- load data ---
data = load_race(2023, 1)
raw_laps = data["laps"]
results = data["results"]

# --- build feature frame + train model ---
df, encoders, feature_cols, target_col = build_feature_frame(raw_laps, results, track_name="Bahrain")
model = train(df, feature_cols, target_col)
save_model(model, "laptime_bahrain_2023")

# --- run simulation ---
engine = RaceEngine(model, encoders, feature_cols, track_encoded=0)
sim_df = engine.simulate(raw_laps, results)

# --- analytics ---
print_summary(sim_df, results, raw_laps)
