"""
Correctness of the Phase 4 circuit-fingerprint features: the degradation
regression, position-change rate, and the same leakage-safety guarantee as
pace.py's rolling features. Synthetic data only, no network.
"""

import numpy as np
import pandas as pd

from src.forecast.track_features import (
    _degradation_slope, _position_change_rate, rolling_track_asof,
)


def test_degradation_slope_recovers_known_linear_rate():
    # LapTime = 90 + 0.2*TyreLife + 0.01*LapNumber, no noise -> slope must be ~0.2.
    # TyreLife resets at lap 31 (a mid-race pit stop) so it isn't collinear with
    # LapNumber -- otherwise the two coefficients are unidentifiable and lstsq
    # just splits the combined effect between them arbitrarily.
    n = 60
    lap_number = np.arange(1, n + 1, dtype=float)
    tyre_life = np.concatenate([np.arange(1, 31, dtype=float), np.arange(1, 31, dtype=float)])
    s = 90.0 + 0.2 * tyre_life + 0.01 * lap_number
    laps = pd.DataFrame({"s": s, "TyreLife": tyre_life, "LapNumber": lap_number})
    assert abs(_degradation_slope(laps) - 0.2) < 1e-6


def test_degradation_slope_nan_when_too_few_laps():
    laps = pd.DataFrame({"s": [90.0, 91.0], "TyreLife": [1.0, 2.0], "LapNumber": [1.0, 2.0]})
    assert pd.isna(_degradation_slope(laps))


def test_position_change_rate_all_static_is_zero():
    laps = pd.DataFrame({
        "Driver": ["VER"] * 5 + ["HAM"] * 5,
        "LapNumber": list(range(1, 6)) * 2,
        "Position": [1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
    })
    assert _position_change_rate(laps) == 0.0


def test_position_change_rate_every_lap_swapped_is_one():
    laps = pd.DataFrame({
        "Driver": ["VER"] * 4 + ["HAM"] * 4,
        "LapNumber": list(range(1, 5)) * 2,
        "Position": [1, 2, 1, 2, 2, 1, 2, 1],
    })
    assert _position_change_rate(laps) == 1.0


def _track_row(season, rnd, circuit, power, degr, typical_laptime=90.0):
    return {
        "circuit": circuit, "Season": season, "Round": rnd,
        "EventDate": pd.Timestamp(year=season, month=1, day=1) + pd.Timedelta(days=365 * (season - 2022)),
        "typical_laptime_s": typical_laptime,
        "power_sensitivity_kmh": power, "degradation_s_per_lap": degr, "position_change_rate": 0.1,
    }


def test_track_asof_never_uses_its_own_row():
    rows = [_track_row(2022, 1, "monza", 300.0, 0.05),
            _track_row(2023, 1, "monza", 300.0, 0.05),
            _track_row(2024, 1, "monza", 10.0, 9.0)]  # a wild, out-of-pattern value
    history = pd.DataFrame(rows)
    out = rolling_track_asof(history)
    # 2024's own fingerprint must reflect only 2022-2023 (both 300.0), unmoved by its own 10.0
    assert out.iloc[2]["power_sensitivity_kmh_asof"] == 300.0


def test_typical_laptime_asof_gives_the_model_a_scale_signal():
    # Monaco (~70s laps) and Spa (~104s laps) must resolve to clearly different
    # typical_laptime_s_asof values -- this is the only feature that tells a
    # model with no circuit identity whether to predict ~70s or ~104s.
    rows = [
        _track_row(2022, 1, "monaco", 150.0, 0.02, typical_laptime=70.0),
        _track_row(2023, 1, "monaco", 150.0, 0.02, typical_laptime=71.0),
        _track_row(2022, 2, "spa", 320.0, 0.08, typical_laptime=104.0),
        _track_row(2023, 2, "spa", 320.0, 0.08, typical_laptime=105.0),
    ]
    history = pd.DataFrame(rows)
    out = rolling_track_asof(history)
    monaco_2023 = out[(out["circuit"] == "monaco") & (out["Season"] == 2023)]["typical_laptime_s_asof"].iloc[0]
    spa_2023 = out[(out["circuit"] == "spa") & (out["Season"] == 2023)]["typical_laptime_s_asof"].iloc[0]
    assert monaco_2023 == 70.0
    assert spa_2023 == 104.0
    assert spa_2023 - monaco_2023 > 30.0


def test_track_asof_keeps_circuits_independent():
    rows = [_track_row(2022, 1, "monaco", 150.0, 0.2), _track_row(2023, 1, "monaco", 150.0, 0.2),
            _track_row(2022, 2, "monza", 320.0, 0.05), _track_row(2023, 2, "monza", 320.0, 0.05)]
    history = pd.DataFrame(rows)
    out = rolling_track_asof(history)
    monaco_2023 = out[(out["circuit"] == "monaco") & (out["Season"] == 2023)]["power_sensitivity_kmh_asof"].iloc[0]
    monza_2023 = out[(out["circuit"] == "monza") & (out["Season"] == 2023)]["power_sensitivity_kmh_asof"].iloc[0]
    assert monaco_2023 == 150.0
    assert monza_2023 == 320.0
