"""
Single source of truth for paths and config that used to be hard-coded relative
strings ("data", "data/models") scattered across load_session.py, train.py,
predict_service.py etc. Everything reads through here now so moving the data
directory (e.g. off OneDrive) is a one-line .env change, not a grep-and-replace.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # FastF1's own HTTP/pickle cache (can grow to tens of GB over 2018-2026).
    f1_cache_dir: str = "data"
    # DuckDB file + Parquet partitions for the processed stats store (Phase 1).
    store_dir: str = "data/store"
    # Trained model artifacts (.pkl).
    model_dir: str = "data/models"

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    f1_username: str | None = None
    f1_password: str | None = None


settings = Settings()
