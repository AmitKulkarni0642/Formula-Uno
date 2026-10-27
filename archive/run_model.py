from src.ingestion.load_session import load_race
from src.features.build_features import build_feature_frame
from src.model.train import train, save_model, feature_importance

data = load_race(2023, 1)
df, encoders, feature_cols, target_col = build_feature_frame(
    data["laps"], data["results"], track_name="Bahrain"
)

print(f"\nTraining on {len(df):,} laps with {len(feature_cols)} features...\n")
model = train(df, feature_cols, target_col)
save_model(model, "laptime_bahrain_2023")
feature_importance(model, feature_cols)
