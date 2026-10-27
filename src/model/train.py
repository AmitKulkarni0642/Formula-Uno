import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.model_selection import cross_val_score
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
import pickle
from pathlib import Path


MODEL_DIR = Path("data/models")


def train(df: pd.DataFrame, feature_cols: list[str], target_col: str) -> XGBRegressor:
    X = df[feature_cols].astype(float)
    y = df[target_col]

    model = XGBRegressor(
        n_estimators=2000,
        learning_rate=0.02,
        max_depth=6,
        min_child_weight=5,   # require at least 5 laps per leaf — reduces overfitting
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
    )

    print("Running 5-fold cross-validation...")
    cv_rmse = cross_val_score(model, X, y, cv=5, scoring="neg_root_mean_squared_error")
    print(f"  CV RMSE: {-cv_rmse.mean():.3f}s ± {cv_rmse.std():.3f}s")

    print("Fitting final model on full dataset...")
    model.fit(X, y)

    y_pred = model.predict(X)
    mae = mean_absolute_error(y, y_pred)
    rmse = root_mean_squared_error(y, y_pred)
    print(f"  Train MAE:  {mae:.3f}s")
    print(f"  Train RMSE: {rmse:.3f}s")

    return model


def save_model(model: XGBRegressor, name: str) -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = MODEL_DIR / f"{name}.pkl"
    with open(path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Model saved to {path}")
    return path


def load_model(name: str) -> XGBRegressor:
    path = MODEL_DIR / f"{name}.pkl"
    with open(path, "rb") as f:
        return pickle.load(f)


def feature_importance(model: XGBRegressor, feature_cols: list[str]) -> None:
    scores = model.feature_importances_
    ranked = sorted(zip(feature_cols, scores), key=lambda x: x[1], reverse=True)
    print("\n=== FEATURE IMPORTANCE ===")
    for feat, score in ranked:
        bar = "#" * int(score * 50)
        print(f"  {feat:<20} {score:.4f}  {bar}")
