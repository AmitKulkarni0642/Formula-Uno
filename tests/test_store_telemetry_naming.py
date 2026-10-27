"""
Regression test for a real bug: write_telemetry_parquet's `file_stem` param
disambiguates the FILENAME for a non-fastest lap (src/compare/loader.py's
lazy cache writes multiple laps per driver per session), but the content's
driver_id column must stay the true driver_id — using the disambiguated
name for both silently broke every WHERE driver_id = ? query for that lap.
"""

import pandas as pd

from src.store import db


def _telemetry_df(lap_number: int) -> pd.DataFrame:
    return pd.DataFrame({
        "lap_number": [lap_number], "sample_idx": [0], "t_ms": [0], "distance_m": [0.0],
        "speed": [200.0], "throttle": [100.0], "brake": [False], "gear": [7],
        "rpm": [11000.0], "drs": [False], "x": [0.0], "y": [0.0],
    })


def test_file_stem_disambiguates_filename_without_corrupting_driver_id(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "STORE_DIR", tmp_path)
    monkeypatch.setattr(db, "TELEMETRY_DIR", tmp_path / "telemetry")

    path_fastest = db.write_telemetry_parquet("2024-01-Q", "2024-01", "Q", "max_verstappen", _telemetry_df(14))
    path_lap5 = db.write_telemetry_parquet(
        "2024-01-Q", "2024-01", "Q", "max_verstappen", _telemetry_df(5), file_stem="max_verstappen__lap5",
    )

    assert path_fastest != path_lap5  # distinct files on disk
    assert pd.read_parquet(path_fastest)["driver_id"].iloc[0] == "max_verstappen"
    assert pd.read_parquet(path_lap5)["driver_id"].iloc[0] == "max_verstappen"  # NOT "max_verstappen__lap5"
    assert pd.read_parquet(path_lap5)["lap_number"].iloc[0] == 5
