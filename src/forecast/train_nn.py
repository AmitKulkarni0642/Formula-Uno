"""
Train the global lap-time neural net and evaluate it on a genuinely held-out
season (the "first set" you asked for: train 2022-2024, predict 2025, see how
the model does). Separate from src/model/train.py (the old per-circuit
XGBoost trainer), which stays untouched.

Validation during training deliberately holds out whole EVENTS (not random
laps) -- random-lap k-fold is the OLD model's documented flaw (PROGRESS.md:
"mixes laps from the same race into train and test"), since adjacent laps in
the same race are highly correlated and leak through a random split. Doesn't
apply to the final 2025 number, which was never touched during training at all.

CLI:
    python -m src.forecast.train_nn --session race   --train-seasons 2022,2023,2024 --eval-seasons 2025
    python -m src.forecast.train_nn --session quali  --train-seasons 2022,2023,2024 --eval-seasons 2025
"""

import argparse

import numpy as np
import pandas as pd
import torch
from torch import nn

from src.forecast import features
from src.forecast.nn_model import LapTimeNet
from src.model.train import save_model


def _continuous_cols(session_type: str) -> list[str]:
    return features.CONTINUOUS_COLS + (features.RACE_ONLY_CONTINUOUS if session_type == "R" else [])


def _event_holdout_split(train_df: pd.DataFrame, frac: float, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = train_df[["Season", "Round"]].drop_duplicates()
    n_val = max(1, int(round(len(events) * frac)))
    val_events = events.sample(n=n_val, random_state=seed)
    val_key = set(zip(val_events["Season"], val_events["Round"]))
    is_val = train_df.apply(lambda r: (r["Season"], r["Round"]) in val_key, axis=1)
    return train_df[~is_val].copy(), train_df[is_val].copy()


def _prep(df: pd.DataFrame, cont_cols: list[str], medians, means, stds):
    cont = df[cont_cols].fillna(medians)
    cont = (cont - means) / stds
    return (
        torch.tensor(cont.to_numpy(dtype="float32")),
        torch.tensor(df["CompoundEncoded"].to_numpy(dtype="int64")),
        torch.tensor(df["EraEncoded"].to_numpy(dtype="int64")),
        torch.tensor(df[features.TARGET_COL].to_numpy(dtype="float32")),
    )


def train_and_evaluate(
    session_type: str,
    train_seasons: list[int],
    eval_seasons: list[int],
    history_start_season: int,
    epochs: int = 80,
    patience: int = 8,
    lr: float = 1e-3,
    batch_size: int = 4096,
    val_frac: float = 0.15,
    seed: int = 42,
) -> dict:
    cont_cols = _continuous_cols(session_type)

    print(f"Building feature frame for {sorted(set(train_seasons) | set(eval_seasons))} "
          f"({session_type}), history from {history_start_season}...")
    frame = features.build_training_frame(
        sorted(set(train_seasons) | set(eval_seasons)), session_type, history_start_season
    )
    frame = frame.dropna(subset=[features.TARGET_COL])
    train_df = frame[frame["Season"].isin(train_seasons)].copy()
    eval_df = frame[frame["Season"].isin(eval_seasons)].copy()
    print(f"  train rows: {len(train_df):,}   eval rows: {len(eval_df):,}")
    if train_df.empty or eval_df.empty:
        raise ValueError("Empty train or eval frame -- check seasons/network access.")

    tr_df, va_df = _event_holdout_split(train_df, val_frac, seed)
    print(f"  internal split: {len(tr_df):,} train laps / {len(va_df):,} val laps "
          f"(held-out whole events, not random laps)")

    # A column entirely NaN in the training split (e.g. every circuit's first-
    # ever appearance, when history_start_season == the first train season)
    # has no real median either -- fall back to 0.0 so NaN never reaches the
    # network, which would otherwise poison every downstream gradient.
    medians = tr_df[cont_cols].median().fillna(0.0)
    means = tr_df[cont_cols].fillna(medians).mean().fillna(0.0)
    stds = tr_df[cont_cols].fillna(medians).std().replace(0, 1.0).fillna(1.0)

    Xc_tr, comp_tr, era_tr, y_tr = _prep(tr_df, cont_cols, medians, means, stds)
    Xc_va, comp_va, era_va, y_va = _prep(va_df, cont_cols, medians, means, stds)
    Xc_ev, comp_ev, era_ev, y_ev = _prep(eval_df, cont_cols, medians, means, stds)

    # Standardize the TARGET too, not just the inputs -- lap time's raw scale
    # (~70-110s depending on circuit) is huge relative to a near-zero-initialized
    # network's output, and Huber's gradient outside its delta is constant
    # magnitude regardless of how far off the prediction is, so without this the
    # network needs an enormous number of steps just to walk its output up to the
    # right ballpark before it can start learning the actually-interesting
    # residual structure. Trained and loss-computed in standardized units;
    # de-standardized back to seconds only for reporting.
    y_mean, y_std = float(y_tr.mean()), float(y_tr.std())
    y_tr_s, y_va_s = (y_tr - y_mean) / y_std, (y_va - y_mean) / y_std

    torch.manual_seed(seed)
    model = LapTimeNet(n_continuous=len(cont_cols))
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.HuberLoss(delta=1.0)

    n = len(tr_df)
    best_val, best_state, patience_left = float("inf"), None, patience

    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(n)
        total_loss = 0.0
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            opt.zero_grad()
            pred = model(Xc_tr[idx], comp_tr[idx], era_tr[idx])
            loss = loss_fn(pred, y_tr_s[idx])
            loss.backward()
            opt.step()
            total_loss += loss.item() * len(idx)
        train_loss = total_loss / n

        model.eval()
        with torch.no_grad():
            val_pred_s = model(Xc_va, comp_va, era_va)
            val_rmse = torch.sqrt(torch.mean((val_pred_s * y_std + y_mean - y_va) ** 2)).item()
        print(f"  epoch {epoch:3d}  train_huber={train_loss:.4f}  val_rmse={val_rmse:.4f}s")

        if val_rmse < best_val - 1e-4:
            best_val = val_rmse
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                print(f"  early stopping at epoch {epoch} (best val_rmse={best_val:.4f}s)")
                break

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        ev_pred = model(Xc_ev, comp_ev, era_ev) * y_std + y_mean
        ev_rmse = torch.sqrt(torch.mean((ev_pred - y_ev) ** 2)).item()
        ev_mae = torch.mean(torch.abs(ev_pred - y_ev)).item()

    baseline_rmse = float(np.sqrt(np.mean((y_ev.numpy() - tr_df[features.TARGET_COL].mean()) ** 2)))

    print(f"\n=== Held out {eval_seasons} ===")
    print(f"  NN   RMSE: {ev_rmse:.3f}s   MAE: {ev_mae:.3f}s   n={len(eval_df)}")
    print(f"  Baseline (predict training mean) RMSE: {baseline_rmse:.3f}s")

    artifact = {
        "state_dict": best_state, "continuous_cols": cont_cols,
        "means": means, "stds": stds, "medians": medians,
        "y_mean": y_mean, "y_std": y_std,
        "session_type": session_type, "train_seasons": train_seasons,
        "history_start_season": history_start_season,
    }
    name = f"nn_laptime_{session_type.lower()}_{'_'.join(map(str, train_seasons))}"
    save_model(artifact, name)

    return {
        "val_rmse": best_val, "eval_rmse": ev_rmse, "eval_mae": ev_mae,
        "baseline_rmse": baseline_rmse, "n_train": len(tr_df), "n_val": len(va_df), "n_eval": len(eval_df),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--session", choices=["race", "quali"], required=True)
    p.add_argument("--train-seasons", required=True, help="comma-separated, e.g. 2022,2023,2024")
    p.add_argument("--eval-seasons", required=True, help="comma-separated, e.g. 2025")
    p.add_argument("--history-start", type=int, default=None, help="defaults to min(train-seasons)")
    p.add_argument("--epochs", type=int, default=80)
    args = p.parse_args()

    train_seasons = [int(s) for s in args.train_seasons.split(",")]
    eval_seasons = [int(s) for s in args.eval_seasons.split(",")]
    history_start = args.history_start or min(train_seasons)
    session_type = "R" if args.session == "race" else "Q"

    result = train_and_evaluate(session_type, train_seasons, eval_seasons, history_start, epochs=args.epochs)
    print("\n", result)
