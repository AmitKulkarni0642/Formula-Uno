"""
Weather for a session that HASN'T happened yet -- the gap the old
reconstruction engine never had to close, since it only ever ran on real,
already-recorded TrackTemp/AirTemp. Two tiers, as discussed with the user:

1. Short-range forecast (Open-Meteo -- free, no API key, ~16 day horizon)
   for air temperature, when the session is close enough that one exists.
2. Circuit climatology (that circuit's own historical median) as a fallback
   when there's no forecast yet, AND as the basis for estimating TRACK
   temperature, which weather APIs don't forecast at all (it's a trackside
   sensor reading, not standard meteorology). A naive AirTemp->TrackTemp
   regression across ALL circuits was tried and rejected: fit on our own
   cached historical laps, it explained almost nothing (residual std ~8.8C)
   because it ignores circuit-specific factors -- asphalt colour/absorption,
   local session time of day. Holding THIS circuit's own historical
   (TrackTemp - AirTemp) offset constant and applying it to the forecasted
   AirTemp is a much smaller, more defensible extrapolation.
"""

import datetime as dt

import pandas as pd
import requests

from src.ingestion.load_session import load_race

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Lat/lon for the current F1 calendar's circuits, keyed exactly as
# src.store.ids.circuit_key(Location) slugifies FastF1's "Location" field.
# A small, static table -- there are only ~24 of these, and new ones are rare.
CIRCUIT_COORDS: dict[str, tuple[float, float]] = {
    "sakhir": (26.0325, 50.5106),
    "jeddah": (21.6319, 39.1044),
    "melbourne": (-37.8497, 144.9680),
    "shanghai": (31.3389, 121.2200),
    "miami_gardens": (25.9581, -80.2389),
    "imola": (44.3439, 11.7167),
    "monte_carlo": (43.7347, 7.4206),
    "barcelona": (41.5700, 2.2611),
    "montr_al": (45.5000, -73.5228),
    "spielberg": (47.2197, 14.7647),
    "silverstone": (52.0786, -1.0169),
    "budapest": (47.5789, 19.2486),
    "spa_francorchamps": (50.4372, 5.9714),
    "zandvoort": (52.3888, 4.5409),
    "monza": (45.6156, 9.2811),
    "baku": (40.3725, 49.8533),
    "marina_bay": (1.2914, 103.8640),
    "austin": (30.1328, -97.6411),
    "mexico_city": (19.4042, -99.0907),
    "s_o_paulo": (-23.7036, -46.6997),
    "las_vegas": (36.1147, -115.1728),
    "lusail": (25.4900, 51.4542),
    "yas_marina": (24.4672, 54.6031),
    "suzuka": (34.8431, 136.5410),
    "losail": (25.4900, 51.4542),
}


def fetch_air_temp_forecast(lat: float, lon: float, when_utc: dt.datetime) -> float | None:
    """Nearest-hour forecasted air temperature at (lat, lon), or None if out of range / unreachable."""
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={"latitude": lat, "longitude": lon, "hourly": "temperature_2m",
                    "timezone": "UTC", "forecast_days": 16},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()["hourly"]
    except Exception:
        return None

    times = pd.to_datetime(data["time"])
    target = pd.Timestamp(when_utc)
    if target.tzinfo is not None:
        target = target.tz_localize(None)
    diffs_s = (times.values - target.to_datetime64()) / pd.Timedelta("1s")
    idx = int(abs(diffs_s).argmin())
    if abs(diffs_s[idx]) > 3 * 3600:
        return None  # nearest point is >3h away -- target is outside the forecast window
    temp = data["temperature_2m"][idx]
    return float(temp) if temp is not None else None


def circuit_climatology(circuit_events: pd.DataFrame, lookback: int = 3) -> dict:
    """
    This circuit's own historical median AirTemp/TrackTemp from its most
    recent `lookback` race sessions (whatever's in `circuit_events` --
    caller is responsible for filtering to one circuit). Also returns the
    TrackTemp-AirTemp offset used to turn a forecasted air temp into an
    estimated track temp. Empty/NaN result if no history is available.
    """
    air, track = [], []
    for _, ev in circuit_events.tail(lookback).iterrows():
        try:
            laps = load_race(int(ev["Season"]), int(ev["Round"]))["laps"]
        except Exception:
            continue
        air.append(laps["AirTemp"].dropna())
        track.append(laps["TrackTemp"].dropna())
    if not air or not any(len(a) for a in air):
        return {"air_temp_c": float("nan"), "track_temp_c": float("nan"), "offset_c": float("nan")}

    air_s, track_s = pd.concat(air), pd.concat(track)
    air_med, track_med = float(air_s.median()), float(track_s.median())
    return {"air_temp_c": air_med, "track_temp_c": track_med, "offset_c": track_med - air_med}


def _combine_forecast_and_climatology(forecast_air: float | None, climo: dict) -> dict:
    """Pure combination logic, split out from forecast_session_weather so it's unit-testable without network."""
    if forecast_air is None:
        return {
            "AirTemp": climo["air_temp_c"], "TrackTemp": climo["track_temp_c"],
            "source": "climatology (no forecast available)",
        }
    offset = climo["offset_c"]
    track_est = forecast_air + offset if pd.notna(offset) else forecast_air
    return {"AirTemp": forecast_air, "TrackTemp": track_est, "source": "forecast + circuit offset"}


def forecast_session_weather(circuit_key: str, circuit_events: pd.DataFrame, when_utc: dt.datetime) -> dict:
    """
    Best-effort TrackTemp/AirTemp for a session that hasn't happened yet.
    `circuit_events` should already be filtered to this circuit's past
    events (for the climatology fallback and the track-temp offset).
    """
    climo = circuit_climatology(circuit_events)
    coords = CIRCUIT_COORDS.get(circuit_key)
    forecast_air = fetch_air_temp_forecast(*coords, when_utc) if coords else None
    return _combine_forecast_and_climatology(forecast_air, climo)
