import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder


COMPOUND_ORDER = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTERMEDIATE": 3, "WET": 4}

REG_ERA_START = 2022   # ground effect rules introduced — Year 0
START_FUEL_KG = 105.0  # typical F1 race start fuel load
QUAL_FUEL_KG  = 5.0    # qualifying cars run minimal fuel for flying laps

WET_COMPOUNDS = ("INTERMEDIATE", "WET")  # wet tyres — excluded so models learn dry pace only
QUAL_FLYING_LAP_PCT = 1.07               # qual: keep laps within 107% of session best (drops out/in laps)

FEATURE_COLS = [
    "DriverEncoded",
    "TeamEncoded",
    "TrackEncoded",
    "YearEncoded",
    "LapNumber",
    "CompoundEncoded",
    "TyreLife",
    "TyreLifeSquared",   # captures non-linear degradation curve
    "FuelLoad",          # physics-based fuel weight effect on lap time
    "GridPosition",
    "TrackTemp",         # track surface temperature (per-lap) — grip & degradation
    "AirTemp",           # ambient air temperature (per-lap)
]
TARGET_COL = "LapTimeSeconds"


def temp_bounds(df: pd.DataFrame) -> dict:
    """
    Min/max of the temperature features over a (training) frame. Used to CLIP
    inference temperatures to the range the model actually trained on — trees
    can't extrapolate, so an out-of-range temp (e.g. a 2025 heatwave) must be
    clamped to the nearest seen value rather than fed raw.
    """
    bounds = {}
    for col in ("TrackTemp", "AirTemp"):
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(s):
                bounds[col] = (float(s.min()), float(s.max()))
    return bounds


def clip_temp(value: float, bounds) -> float:
    """Clamp a temperature to (lo, hi); leaves NaN or missing bounds untouched."""
    if bounds is None or value != value:  # value != value is True only for NaN
        return value
    lo, hi = bounds
    return lo if value < lo else (hi if value > hi else value)


# ── Encoder construction ──────────────────────────────────────────────────────

def build_encoders(sessions: list[dict]) -> dict:
    """
    Fit LabelEncoders on the union of all sessions provided.

    sessions: list of {"laps": DataFrame, "track_name": str}

    Call this BEFORE building feature frames when you have data from multiple
    years or circuits. The resulting encoders cover every driver, team, and
    track name that will appear in training OR evaluation.
    """
    all_drivers = pd.concat([s["laps"]["Driver"].dropna() for s in sessions]).unique()
    all_teams   = pd.concat([s["laps"]["Team"].dropna()   for s in sessions]).unique()
    all_tracks  = [s["track_name"] for s in sessions]

    driver_le = LabelEncoder().fit(sorted(all_drivers))
    team_le   = LabelEncoder().fit(sorted(all_teams))
    track_le  = LabelEncoder().fit(sorted(set(all_tracks)))

    return {"Driver": driver_le, "Team": team_le, "Track": track_le}


# ── Transformation steps ──────────────────────────────────────────────────────

def _lap_time_to_seconds(laps: pd.DataFrame) -> pd.DataFrame:
    laps = laps.copy()
    laps["LapTimeSeconds"] = laps["LapTime"].dt.total_seconds()
    return laps


def _drop_bad_laps(laps: pd.DataFrame) -> pd.DataFrame:
    mask = (
        laps["LapTimeSeconds"].notna()
        & laps["IsAccurate"]
        & ~laps["Deleted"].fillna(False).astype(bool)
        & laps["LapNumber"].notna()
        & laps["TyreLife"].notna()
        & laps["Compound"].notna()
        & laps["Compound"].ne("UNKNOWN")
        & ~laps["Compound"].isin(WET_COMPOUNDS)
        & laps["Position"].notna()
    )
    # SC and VSC laps are artificially slow — training on them would corrupt
    # the model's understanding of pure pace at given tyre/fuel state.
    # TrackStatus "4" = Safety Car deployed, "6" = Virtual Safety Car.
    if "TrackStatus" in laps.columns:
        ts = laps["TrackStatus"].astype(str)
        mask &= ~(ts.str.contains("4") | ts.str.contains("6"))

    dropped = (~mask).sum()
    print(f"  Dropped {dropped} bad/inaccurate laps ({dropped / len(laps) * 100:.1f}%)")
    return laps[mask].copy()


def _drop_bad_qual_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Same as _drop_bad_laps but without the Position filter (qualifying has no race position)."""
    mask = (
        laps["LapTimeSeconds"].notna()
        & laps["IsAccurate"]
        & ~laps["Deleted"].fillna(False).astype(bool)
        & laps["LapNumber"].notna()
        & laps["TyreLife"].notna()
        & laps["Compound"].notna()
        & laps["Compound"].ne("UNKNOWN")
        & ~laps["Compound"].isin(WET_COMPOUNDS)
    )
    if "TrackStatus" in laps.columns:
        ts = laps["TrackStatus"].astype(str)
        mask &= ~(ts.str.contains("4") | ts.str.contains("6"))

    dropped = (~mask).sum()
    return laps[mask].copy(), dropped


def _encode_compound(laps: pd.DataFrame) -> pd.DataFrame:
    laps = laps.copy()
    laps["CompoundEncoded"] = laps["Compound"].map(COMPOUND_ORDER).fillna(-1).astype(int)
    return laps


def _encode_categoricals(laps: pd.DataFrame, encoders: dict) -> pd.DataFrame:
    """Apply pre-fit Driver and Team encoders. Never refits."""
    laps = laps.copy()
    laps["DriverEncoded"] = encoders["Driver"].transform(laps["Driver"])
    laps["TeamEncoded"]   = encoders["Team"].transform(laps["Team"])
    return laps


def _encode_track(laps: pd.DataFrame, track_name: str, track_encoder: LabelEncoder) -> pd.DataFrame:
    laps = laps.copy()
    laps["TrackName"]    = track_name
    laps["TrackEncoded"] = track_encoder.transform(laps["TrackName"])
    return laps


def _merge_grid_position(laps: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    grid = (
        results[["Abbreviation", "GridPosition"]]
        .rename(columns={"Abbreviation": "Driver"})
        .copy()
    )
    grid["GridPosition"] = pd.to_numeric(grid["GridPosition"], errors="coerce")
    return laps.merge(grid, on="Driver", how="left")


# ── Race feature pipeline ─────────────────────────────────────────────────────

def build_feature_frame(
    laps: pd.DataFrame,
    results: pd.DataFrame,
    track_name: str,
    encoders: dict,
    year: int,
) -> pd.DataFrame:
    """
    Transform raw FastF1 race laps into a clean ML-ready DataFrame.

    FuelLoad is computed from LapNumber assuming a linear burn from START_FUEL_KG.
    TyreLifeSquared captures the non-linear degradation acceleration on old rubber.
    total_laps is computed BEFORE filtering so the fuel formula uses the true race distance.
    """
    laps = _lap_time_to_seconds(laps)
    total_laps = int(laps["LapNumber"].max())  # real race distance before any row is dropped

    laps = _drop_bad_laps(laps)
    laps = _encode_compound(laps)
    laps = _encode_categoricals(laps, encoders)
    laps = _merge_grid_position(laps, results)
    laps = _encode_track(laps, track_name, encoders["Track"])

    laps = laps.copy()
    laps["YearEncoded"]    = float(year - REG_ERA_START)
    laps["FuelLoad"]       = START_FUEL_KG - (laps["LapNumber"] - 1) * (START_FUEL_KG / total_laps)
    laps["TyreLifeSquared"] = laps["TyreLife"] ** 2

    display_extra = [TARGET_COL, "Driver", "Team", "Compound", "Position"]
    keep   = FEATURE_COLS + [c for c in display_extra if c not in FEATURE_COLS]
    output = laps[[c for c in keep if c in laps.columns]].copy()

    print(f"  {year} {track_name}: {len(output):,} laps x {len(FEATURE_COLS)} features")
    return output


# ── Qualifying feature pipeline ───────────────────────────────────────────────

def build_qualifying_feature_frame(
    qual_laps: pd.DataFrame,
    qual_results: pd.DataFrame,
    track_name: str,
    encoders: dict,
    year: int,
) -> pd.DataFrame:
    """
    Build a feature frame from qualifying laps for training a dedicated qualifying model.

    Differences from build_feature_frame (race):
    - FuelLoad is fixed at QUAL_FUEL_KG (cars run minimal fuel in qualifying)
    - GridPosition comes from qualifying session results (= qualifying finishing position)
    - Position filter removed (qualifying has no running race position column)
    """
    laps = qual_laps.copy()
    laps["LapTimeSeconds"] = laps["LapTime"].dt.total_seconds()

    laps, dropped = _drop_bad_qual_laps(laps)

    # Flying-lap filter: keep only genuine push laps (within 107% of the session's fastest).
    # IsAccurate leaves in out-laps, in-laps and aborted runs (30%+ slower) that were corrupting
    # the qual models. This matches the clean fastest laps we actually predict on at serve time.
    n_before = len(laps)
    if n_before:
        cutoff = laps["LapTimeSeconds"].min() * QUAL_FLYING_LAP_PCT
        laps = laps[laps["LapTimeSeconds"] <= cutoff].copy()
    non_flying = n_before - len(laps)
    print(f"  {year} {track_name} qualifying: {len(laps):,} laps (dropped {dropped} bad + {non_flying} non-flying)")

    laps = _encode_compound(laps)

    # Drop rows for drivers/teams not seen in encoder universe (e.g. wildcard entries)
    known_drivers = set(encoders["Driver"].classes_)
    known_teams   = set(encoders["Team"].classes_)
    laps = laps[laps["Driver"].isin(known_drivers) & laps["Team"].isin(known_teams)].copy()

    laps = _encode_categoricals(laps, encoders)
    laps = _encode_track(laps, track_name, encoders["Track"])

    laps["YearEncoded"]     = float(year - REG_ERA_START)
    laps["FuelLoad"]        = float(QUAL_FUEL_KG)
    laps["TyreLifeSquared"] = laps["TyreLife"] ** 2

    # Qualifying position rank = proxy for car quality (replaces race GridPosition)
    grid = qual_results[["Abbreviation", "Position"]].copy()
    grid = grid.rename(columns={"Abbreviation": "Driver", "Position": "GridPosition"})
    grid["GridPosition"] = pd.to_numeric(grid["GridPosition"], errors="coerce")
    laps = laps.merge(grid[["Driver", "GridPosition"]], on="Driver", how="left")
    laps["GridPosition"] = laps["GridPosition"].fillna(15.0)

    display_extra = [TARGET_COL, "Driver", "Team", "Compound"]
    keep   = FEATURE_COLS + [c for c in display_extra if c not in FEATURE_COLS]
    output = laps[[c for c in keep if c in laps.columns]].copy()
    return output
