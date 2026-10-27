from src.ingestion.load_session import load_race
from src.features.build_features import build_feature_frame, summarise

data = load_race(2023, 1)
df, encoders, feature_cols, target_col = build_feature_frame(
    data["laps"], data["results"], track_name="Bahrain"
)
summarise(df)

print("\n=== FEATURE COLUMNS (model inputs) ===")
print(feature_cols)
print(f"\n=== TARGET COLUMN (model output) ===")
print(target_col)
