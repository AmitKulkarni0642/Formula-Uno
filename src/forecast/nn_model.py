"""
The tabular MLP that replaces XGBoost for the global lap-time model (your
call, D1-follow-up: a neural net instead of another tree ensemble -- the
only option of the four we discussed that doesn't inherit trees' inability
to extrapolate past the training range).

Compound and Era are genuinely categorical (there's no meaningful "distance"
between SOFT and HARD) so they go through small learned embeddings rather
than being treated as ordinal integers; everything else is continuous and
expected to already be standardized by the caller (see train_nn.py) -- unlike
trees, a network's gradients are scale-sensitive, so this isn't optional the
way it was for XGBoost.
"""

import torch
import torch.nn as nn

COMPOUND_CLASSES = 5
ERA_CLASSES = 3


class LapTimeNet(nn.Module):
    def __init__(
        self,
        n_continuous: int,
        compound_dim: int = 4,
        era_dim: int = 3,
        hidden: tuple[int, ...] = (128, 64, 32),
        dropout: float = 0.2,
    ):
        super().__init__()
        self.compound_emb = nn.Embedding(COMPOUND_CLASSES, compound_dim)
        self.era_emb = nn.Embedding(ERA_CLASSES, era_dim)

        in_dim = n_continuous + compound_dim + era_dim
        layers: list[nn.Module] = []
        prev = in_dim
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.BatchNorm1d(h), nn.GELU(), nn.Dropout(dropout)]
            prev = h
        layers.append(nn.Linear(prev, 1))
        self.trunk = nn.Sequential(*layers)

    def forward(self, x_continuous: torch.Tensor, compound_idx: torch.Tensor, era_idx: torch.Tensor) -> torch.Tensor:
        x = torch.cat([x_continuous, self.compound_emb(compound_idx), self.era_emb(era_idx)], dim=1)
        return self.trunk(x).squeeze(-1)
