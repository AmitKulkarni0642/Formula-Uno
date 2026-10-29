"""
Per-circuit "fingerprint" features: what kind of track is this, independent of
who's racing on it. Lets the model transfer what it learned at one power
circuit (Monza, Spa) to another it never trained on, and separately express
"this track punishes old tyres" vs "this track makes overtaking easy" as
numbers instead of a circuit name.

Same leakage rule as pace.py: a circuit's fingerprint "as of" event E uses
only that circuit's OWN sessions strictly before E. Circuits get resurfaced
and modified (new asphalt changes degradation; a chicane removed changes
overtaking), so a fingerprint built from the whole history including future
years would leak track evolution backward in time, same category of mistake
as leaking a result backward.
"""

import numpy as np
import pandas as pd

from src.ingestion.load_session import load_race, load_qualifying
from src.store.ids import circuit_key as _circuit_key
from src.forecast.pace import clean_laps


def _degradation_slope(laps: pd.DataFrame) -> float:
    """
    Seconds of lap time gained per lap of tyre age, controlling for fuel burn
    via LapNumber as a second regressor (plain OLS, same lightweight-NumPy
    convention as development.py's change-point detection — no stats library
    needed for a 3-coefficient fit). NaN if too few clean laps to fit.
    """
    df = laps.dropna(subset=["s", "TyreLife", "LapNumber"])
    if len(df) < 20:
        return float("nan")
    X = np.column_stack([df["TyreLife"].to_numpy(), df["LapNumber"].to_numpy(), np.ones(len(df))])
    y = df["s"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[0])


def _position_change_rate(laps: pd.DataFrame) -> float:
    """Fraction of driver-laps where Position differs from that driver's previous lap."""
    df = laps.dropna(subset=["Position", "LapNumber"]).sort_values(["Driver", "LapNumber"])
    if df.empty:
        return float("nan")
    changed = df.groupby("Driver")["Position"].diff().fillna(0) != 0
    # exclude each driver's first lap from the denominator (diff is NaN->0 there,
    # which correctly reads as "no change" above, but it isn't a real comparison)
    denom = int((df.groupby("Driver").cumcount() > 0).sum())
    return float(changed.sum()) / denom if denom else float("nan")


def circuit_session_stats(year: int, event, session_type: str) -> dict:
    """
    One session's contribution to its circuit's fingerprint: power_sensitivity_kmh
    (median speed-trap reading — high for Monza/Spa/Baku, low for Monaco/Hungary),
    degradation_s_per_lap (race only — NaN for qualifying, which doesn't have
    enough tyre-age range to fit a slope), position_change_rate (race only).
    """
    loader = load_race if session_type == "R" else load_qualifying
    data = loader(year, event)
    laps = clean_laps(data["laps"])
    circuit = _circuit_key(str(data["session"].event["Location"]))

    power = laps["SpeedST"].dropna().median() if "SpeedST" in laps.columns and len(laps) else float("nan")
    # The scale-giving feature: without this, nothing in the fingerprint tells
    # the model whether this circuit's laps run ~70s (Monaco) or ~104s (Spa) --
    # removing Driver/Team/Circuit identity (the whole point of generalising)
    # also removes the only other thing that carried that information.
    typical_lap = laps["s"].median() if len(laps) else float("nan")
    out = {
        "circuit": circuit,
        "typical_laptime_s": float(typical_lap) if pd.notna(typical_lap) else float("nan"),
        "power_sensitivity_kmh": float(power) if pd.notna(power) else float("nan"),
    }
    if session_type == "R":
        out["degradation_s_per_lap"] = _degradation_slope(laps)
        out["position_change_rate"] = _position_change_rate(data["laps"])
    return out


def build_track_history(events: pd.DataFrame, session_type: str) -> pd.DataFrame:
    """Same shape/contract as pace.build_pace_history, but keyed on circuit instead of team/driver."""
    rows = []
    for _, ev in events.iterrows():
        try:
            stats = circuit_session_stats(int(ev["Season"]), int(ev["Round"]), session_type)
        except Exception:
            continue
        stats.update({"Season": int(ev["Season"]), "Round": int(ev["Round"]), "EventDate": ev["EventDate"]})
        rows.append(stats)
    cols = ["circuit", "Season", "Round", "EventDate", "typical_laptime_s", "power_sensitivity_kmh"]
    if session_type == "R":
        cols += ["degradation_s_per_lap", "position_change_rate"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows).sort_values(["EventDate", "Season", "Round"]).reset_index(drop=True)


def rolling_track_asof(history: pd.DataFrame, halflife_events: float = 3.0) -> pd.DataFrame:
    """
    'As of this event' circuit fingerprint: EWM over a circuit's own PAST
    sessions only (shift(1) before the EWM — the leakage guard). halflife is
    in units of "that circuit's own past appearances" (usually ~1/season), so
    halflife_events=3 means roughly the last 3 years at that circuit dominate.
    """
    history = history.sort_values(["EventDate", "Season", "Round"]).copy()
    metric_cols = [c for c in history.columns if c not in ("circuit", "Season", "Round", "EventDate")]
    for col in metric_cols:
        history[f"{col}_asof"] = (
            history.groupby("circuit")[col]
            .transform(lambda s: s.shift(1).ewm(halflife=halflife_events, min_periods=1).mean())
        )
    return history
