"""
Model benchmark — train several regressors on the same feature table and compare
5-fold cross-validated RMSE.

This is how we answer "should we use something other than XGBoost?" honestly:
same data, same cross-validation, side by side. It spans the spectrum on purpose —
a linear baseline, a neural net, a bagging ensemble, and gradient boosters — so the
comparison shows *why* one wins, not just that it does.
"""

import time
import pandas as pd
from sklearn.model_selection import cross_val_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor


def _build_models() -> dict:
    """Candidate models. Tree models need no scaling; Ridge and the MLP get a StandardScaler."""
    models = {
        "Ridge (linear baseline)": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "Neural Net (MLP 64-32)": make_pipeline(
            StandardScaler(),
            MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=500,
                         early_stopping=True, random_state=42),
        ),
        "Random Forest": RandomForestRegressor(
            n_estimators=300, max_depth=12, random_state=42, n_jobs=-1),
        "XGBoost (current)": XGBRegressor(
            n_estimators=2000, learning_rate=0.02, max_depth=6, min_child_weight=5,
            subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1),
    }
    try:
        from lightgbm import LGBMRegressor
        models["LightGBM"] = LGBMRegressor(
            n_estimators=2000, learning_rate=0.02, max_depth=6, num_leaves=31,
            subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1, verbosity=-1)
    except ImportError:
        pass
    try:
        from catboost import CatBoostRegressor
        models["CatBoost"] = CatBoostRegressor(
            iterations=2000, learning_rate=0.02, depth=6, random_seed=42, verbose=0)
    except ImportError:
        pass
    return models


def benchmark_models(df: pd.DataFrame, feature_cols: list, target_col: str, cv: int = 5) -> pd.DataFrame:
    """Run identical k-fold CV for every candidate; return a table sorted by CV RMSE."""
    X = df[feature_cols].astype(float)
    y = df[target_col]
    rows = []
    for name, model in _build_models().items():
        t0 = time.time()
        scores = cross_val_score(model, X, y, cv=cv, scoring="neg_root_mean_squared_error")
        rows.append({
            "Model":      name,
            "CV_RMSE":    float(-scores.mean()),
            "Std":        float(scores.std()),
            "FitSeconds": time.time() - t0,
        })
    return pd.DataFrame(rows).sort_values("CV_RMSE").reset_index(drop=True)


def print_benchmark(res: pd.DataFrame, title: str) -> None:
    print(f"\n{'='*58}")
    print(f"  MODEL BENCHMARK — {title}")
    print(f"{'='*58}")
    print(f"  {'Model':<26}{'CV RMSE':>9}{'  ±Std':>8}{'  Time':>8}")
    print("  " + "-" * 52)
    best = res["CV_RMSE"].min()
    for _, r in res.iterrows():
        mark = "  <-- best" if abs(r["CV_RMSE"] - best) < 1e-9 else ""
        print(f"  {r['Model']:<26}{r['CV_RMSE']:>8.3f}s{r['Std']:>7.3f}{r['FitSeconds']:>7.1f}s{mark}")
    print()
