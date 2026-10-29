"""
Load a trained global lap-time NN (see train_nn.py) and run inference on it.
Rebuilds the exact architecture from what the artifact itself recorded
(hidden sizes, dropout) rather than trusting LapTimeNet's current defaults --
those have already changed once this session, so a stale assumption here
would silently load weights into the wrong-shaped network.
"""

import numpy as np
import pandas as pd
import torch

from src.model.train import load_model
from src.forecast.nn_model import LapTimeNet


class LoadedLapTimeModel:
    def __init__(self, name: str):
        art = load_model(name)
        self.continuous_cols: list[str] = art["continuous_cols"]
        self.means, self.stds, self.medians = art["means"], art["stds"], art["medians"]
        self.y_mean, self.y_std = art["y_mean"], art["y_std"]
        self.session_type: str = art["session_type"]
        self.model = LapTimeNet(
            n_continuous=len(self.continuous_cols),
            hidden=tuple(art.get("hidden", (64, 32))),
            dropout=art.get("dropout", 0.35),
        )
        self.model.load_state_dict(art["state_dict"])
        self.model.eval()

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """rows must have self.continuous_cols plus CompoundEncoded/EraEncoded."""
        cont = rows[self.continuous_cols].fillna(self.medians)
        cont = (cont - self.means) / self.stds
        Xc = torch.tensor(cont.to_numpy(dtype="float32"))
        comp = torch.tensor(rows["CompoundEncoded"].to_numpy(dtype="int64"))
        era = torch.tensor(rows["EraEncoded"].to_numpy(dtype="int64"))
        with torch.no_grad():
            pred = self.model(Xc, comp, era) * self.y_std + self.y_mean
        return pred.numpy()
