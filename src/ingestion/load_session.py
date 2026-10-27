import os
import warnings
import logging
import fastf1
import pandas as pd

from src.settings import settings

# Quiet FastF1's noisy INFO/req/core logging and pandas FutureWarnings, so that
# actual results are readable in the terminal instead of buried under log spam.
warnings.filterwarnings("ignore", category=FutureWarning)
try:
    fastf1.set_log_level("ERROR")
except Exception:
    logging.getLogger("fastf1").setLevel(logging.ERROR)

os.makedirs(settings.f1_cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(settings.f1_cache_dir)


def _load(year: int, event, session_type: str) -> dict:
    """Internal loader. event can be round number (int) or event name (str)."""
    session = fastf1.get_session(year, event, session_type)
    session.load(telemetry=False, weather=True, messages=False)
    laps = _attach_weather(session, session.laps.copy())
    return {
        "session": session,
        "laps": laps,
        "results": session.results.copy(),
    }


def _attach_weather(session, laps: pd.DataFrame) -> pd.DataFrame:
    """
    Add per-lap TrackTemp and AirTemp columns.

    Uses FastF1's get_weather_data() to align the nearest weather reading to each
    lap, capturing within-race temperature drift. Falls back to the session median,
    then to NaN (which XGBoost handles natively) if weather is unavailable.
    """
    tt = at = None
    try:
        wx = session.laps.get_weather_data()
        tt = pd.to_numeric(wx["TrackTemp"], errors="coerce").to_numpy()
        at = pd.to_numeric(wx["AirTemp"], errors="coerce").to_numpy()
        if len(tt) != len(laps):
            tt = at = None
    except Exception:
        tt = at = None

    if tt is not None:
        laps["TrackTemp"] = tt
        laps["AirTemp"] = at
    else:
        wd = getattr(session, "weather_data", None)
        if wd is not None and len(wd):
            laps["TrackTemp"] = float(pd.to_numeric(wd["TrackTemp"], errors="coerce").median())
            laps["AirTemp"] = float(pd.to_numeric(wd["AirTemp"], errors="coerce").median())
        else:
            laps["TrackTemp"] = float("nan")
            laps["AirTemp"] = float("nan")
    return laps


def load_race(year: int, event) -> dict:
    """Load a race session. event = round number (int) or event name (str)."""
    return _load(year, event, "R")


def load_qualifying(year: int, event) -> dict:
    """Load a qualifying session. event = round number (int) or event name (str)."""
    return _load(year, event, "Q")


def inspect_laps(laps: pd.DataFrame) -> None:
    print("\n=== LAP DATA SHAPE ===")
    print(f"Rows: {len(laps):,}  |  Columns: {len(laps.columns)}")

    print("\n=== COLUMNS ===")
    print(list(laps.columns))

    print("\n=== SAMPLE (first 5 laps) ===")
    key_cols = [
        "Driver", "Team", "LapNumber", "LapTime",
        "Compound", "TyreLife", "Position", "PitInTime", "PitOutTime",
    ]
    available = [c for c in key_cols if c in laps.columns]
    print(laps[available].head(10).to_string(index=False))

    print("\n=== LAP TIME STATS (seconds) ===")
    lap_seconds = laps["LapTime"].dt.total_seconds().dropna()
    print(lap_seconds.describe().round(3))

    print("\n=== DRIVERS IN SESSION ===")
    print(sorted(laps["Driver"].unique()))

    print("\n=== TYRE COMPOUNDS USED ===")
    print(laps["Compound"].value_counts().to_string())


if __name__ == "__main__":
    print("Loading 2023 Bahrain Grand Prix...")
    data = load_race(2023, 1)
    inspect_laps(data["laps"])
