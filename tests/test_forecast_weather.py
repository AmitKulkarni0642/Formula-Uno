"""
Pure-logic tests for the weather fallback chain: forecast+offset when a
forecast exists, straight climatology when it doesn't. No network.
"""

import math

from src.forecast.weather import _combine_forecast_and_climatology


def test_uses_forecast_air_temp_plus_circuit_offset_for_track_temp():
    climo = {"air_temp_c": 20.0, "track_temp_c": 35.0, "offset_c": 15.0}
    out = _combine_forecast_and_climatology(28.0, climo)
    assert out["AirTemp"] == 28.0
    assert out["TrackTemp"] == 43.0  # forecasted air (28) + this circuit's own historical offset (15)
    assert "forecast" in out["source"]


def test_falls_back_to_pure_climatology_when_no_forecast():
    climo = {"air_temp_c": 22.0, "track_temp_c": 38.0, "offset_c": 16.0}
    out = _combine_forecast_and_climatology(None, climo)
    assert out["AirTemp"] == 22.0
    assert out["TrackTemp"] == 38.0
    assert "climatology" in out["source"]


def test_falls_back_to_raw_forecast_air_temp_when_offset_unknown():
    climo = {"air_temp_c": float("nan"), "track_temp_c": float("nan"), "offset_c": float("nan")}
    out = _combine_forecast_and_climatology(25.0, climo)
    assert out["AirTemp"] == 25.0
    assert out["TrackTemp"] == 25.0  # no offset to apply -- better than NaN
