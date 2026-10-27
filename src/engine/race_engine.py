import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from xgboost import XGBRegressor
from src.features.build_features import clip_temp

COMPOUND_ORDER = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTERMEDIATE": 3, "WET": 4}
REG_ERA_START  = 2022


@dataclass
class DriverState:
    """Mutable per-driver state that evolves lap by lap through the simulation."""
    name: str
    team: str
    driver_encoded: int
    team_encoded: int
    grid_position: float
    compound: str
    tyre_age: int
    cumulative_time: float = 0.0
    position: int = 0
    lap_times: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    retired: bool = False


class RaceEngine:

    def __init__(
        self,
        model: XGBRegressor,
        encoders: dict,
        feature_cols: list,
        track_encoded: int = 0,
        sim_year: int = 2023,
        temp_bounds: dict = None,
    ):
        self.model = model
        self.encoders = encoders
        self.feature_cols = feature_cols
        self.track_encoded = track_encoded
        self.year_encoded = float(sim_year - REG_ERA_START)
        self.temp_bounds = temp_bounds or {}
        self._track_temp = float("nan")
        self._air_temp = float("nan")
        self._tt_by_lap: dict = {}
        self._at_by_lap: dict = {}

    # ------------------------------------------------------------------
    # SETUP: build per-driver initial state from raw FastF1 data
    # ------------------------------------------------------------------

    def _build_driver_states(self, raw_laps: pd.DataFrame, results: pd.DataFrame) -> dict:
        """
        Initialise a DriverState for every driver using their actual starting
        compound, tyre age, and grid position from the real race.
        """
        driver_encoder = self.encoders["Driver"]
        team_encoder = self.encoders["Team"]
        states = {}

        grid = results[["Abbreviation", "GridPosition"]].copy()
        grid["GridPosition"] = pd.to_numeric(grid["GridPosition"], errors="coerce")
        grid_map = dict(zip(grid["Abbreviation"], grid["GridPosition"]))

        for driver, group in raw_laps.groupby("Driver"):
            group = group.sort_values("LapNumber")

            team = group["Team"].iloc[0]
            grid_pos = grid_map.get(driver, 20.0)

            # First non-null compound in the race = starting compound
            start_compound = group["Compound"].dropna()
            start_compound = start_compound.iloc[0] if not start_compound.empty else "MEDIUM"

            # FastF1 TyreLife on lap 1 accounts for warm-up/installation laps
            first_tyre_life = group["TyreLife"].iloc[0]
            start_tyre_age = int(first_tyre_life) if pd.notna(first_tyre_life) else 1

            try:
                driver_enc = int(driver_encoder.transform([driver])[0])
                team_enc = int(team_encoder.transform([team])[0])
            except ValueError:
                continue  # driver/team not seen during training — skip

            states[driver] = DriverState(
                name=driver,
                team=team,
                driver_encoded=driver_enc,
                team_encoded=team_enc,
                grid_position=float(grid_pos),
                compound=start_compound,
                tyre_age=start_tyre_age,
                position=int(grid_pos),
            )

        return states

    # ------------------------------------------------------------------
    # SETUP: extract pit stop schedule from raw lap data
    # ------------------------------------------------------------------

    def _build_pit_schedule(self, raw_laps: pd.DataFrame) -> dict:
        """
        Scan raw laps for PitInTime entries and build a per-driver schedule:

            schedule[driver][in_lap_number] = {
                new_compound   : str   — compound fitted during this stop
                in_lap_time    : float — actual historical in-lap duration (s)
                out_lap_num    : int   — lap number of the subsequent out-lap
                out_lap_time   : float — actual historical out-lap duration (s)
            }

        We use actual historical times for pit stop laps because:
        (a) the lap time model was never trained on these laps (they were filtered),
        (b) using real data decouples strategy accuracy from speed model accuracy,
            letting us validate each component independently.
        """
        schedule = {}

        for driver, group in raw_laps.groupby("Driver"):
            group = group.sort_values("LapNumber")
            schedule[driver] = {}

            in_laps = group[group["PitInTime"].notna()]

            for _, row in in_laps.iterrows():
                in_lap_num = int(row["LapNumber"])
                out_lap_num = in_lap_num + 1

                out_rows = group[group["LapNumber"] == out_lap_num]
                if out_rows.empty:
                    continue
                out_row = out_rows.iloc[0]

                def safe_seconds(val):
                    try:
                        return val.total_seconds() if pd.notna(val) else None
                    except Exception:
                        return None

                schedule[driver][in_lap_num] = {
                    "new_compound": out_row["Compound"],
                    "in_lap_time": safe_seconds(row["LapTime"]),
                    "out_lap_num": out_lap_num,
                    "out_lap_time": safe_seconds(out_row["LapTime"]),
                }

        return schedule

    # ------------------------------------------------------------------
    # CORE: single-lap model inference
    # ------------------------------------------------------------------

    def _predict_lap(self, state: DriverState, lap_number: int, total_laps: int) -> float:
        """
        Assemble the feature vector for one driver on one lap and call model.predict().

        FuelLoad decreases linearly from START_FUEL_KG on lap 1 to near-zero on the final lap.
        TyreLifeSquared lets the model learn the accelerating degradation curve on old rubber.
        Both must match exactly what build_feature_frame computes during training.
        """
        fuel_load      = 105.0 - (lap_number - 1) * (105.0 / total_laps)
        tyre_life_sq   = float(state.tyre_age) ** 2
        track_temp     = clip_temp(self._tt_by_lap.get(lap_number, self._track_temp), self.temp_bounds.get("TrackTemp"))
        air_temp       = clip_temp(self._at_by_lap.get(lap_number, self._air_temp), self.temp_bounds.get("AirTemp"))

        features = {
            "DriverEncoded":   float(state.driver_encoded),
            "TeamEncoded":     float(state.team_encoded),
            "TrackEncoded":    float(self.track_encoded),
            "YearEncoded":     self.year_encoded,
            "LapNumber":       float(lap_number),
            "CompoundEncoded": float(COMPOUND_ORDER.get(state.compound, 1)),
            "TyreLife":        float(state.tyre_age),
            "TyreLifeSquared": tyre_life_sq,
            "FuelLoad":        fuel_load,
            "GridPosition":    float(state.grid_position),
            "TrackTemp":       track_temp,
            "AirTemp":         air_temp,
        }
        X = pd.DataFrame([features])[self.feature_cols]
        return float(self.model.predict(X)[0])

    # ------------------------------------------------------------------
    # MAIN: simulation loop
    # ------------------------------------------------------------------

    def simulate(self, raw_laps: pd.DataFrame, results: pd.DataFrame, max_laps: int = None) -> pd.DataFrame:
        """
        Run a full race simulation lap by lap.

        max_laps: if set, stop after this many laps (useful for focused 10-lap validation).
        Returns a DataFrame with one row per (driver, lap) containing:
        LapTime, CumulativeTime, Compound, TyreAge, Position.
        """
        race_laps = int(raw_laps["LapNumber"].max())
        total_laps = min(max_laps, race_laps) if max_laps else race_laps

        # Per-lap weather (median across the field), session-median as fallback.
        if "TrackTemp" in raw_laps.columns:
            self._track_temp = float(raw_laps["TrackTemp"].median())
            self._tt_by_lap = raw_laps.groupby("LapNumber")["TrackTemp"].median().to_dict()
        if "AirTemp" in raw_laps.columns:
            self._air_temp = float(raw_laps["AirTemp"].median())
            self._at_by_lap = raw_laps.groupby("LapNumber")["AirTemp"].median().to_dict()

        print("Building driver states...")
        states = self._build_driver_states(raw_laps, results)
        print(f"  {len(states)} drivers initialised")

        print("Building pit stop schedule...")
        pit_schedule = self._build_pit_schedule(raw_laps)
        total_stops = sum(len(v) for v in pit_schedule.values())
        print(f"  {total_stops} pit stops scheduled across {total_laps} laps")

        print(f"\nSimulating {total_laps} laps...\n")

        history = []

        # Tracks which drivers are on a scheduled out-lap this lap
        # { driver_name: {"lap": int, "out_lap_time": float} }
        out_lap_queue = {}

        for lap in range(1, total_laps + 1):

            for driver_name, state in states.items():
                if state.retired:
                    continue

                driver_pit = pit_schedule.get(driver_name, {})

                # ---- determine lap time ----

                if driver_name in out_lap_queue and out_lap_queue[driver_name]["lap"] == lap:
                    # OUT-LAP: driver rejoins after a pit stop
                    # Use actual historical out-lap time (model was never trained on these)
                    entry = out_lap_queue.pop(driver_name)
                    lap_time = entry["out_lap_time"] or (self._predict_lap(state, lap, total_laps) + 15.0)

                elif lap in driver_pit:
                    # IN-LAP: driver pits at the end of this lap
                    pit_info = driver_pit[lap]
                    lap_time = pit_info["in_lap_time"] or (self._predict_lap(state, lap, total_laps) + 20.0)

                    # Switch to fresh tyre — takes effect from next lap onwards
                    new_compound = pit_info["new_compound"]
                    if pd.notna(new_compound) and new_compound in COMPOUND_ORDER:
                        state.compound = new_compound
                    state.tyre_age = 0  # incremented to 1 at end of this lap block

                    # Queue the out-lap for next lap
                    out_lap_queue[driver_name] = {
                        "lap": lap + 1,
                        "out_lap_time": pit_info["out_lap_time"],
                    }

                else:
                    # NORMAL LAP: model inference
                    lap_time = self._predict_lap(state, lap, total_laps)

                # ---- update state ----
                state.cumulative_time += lap_time
                state.tyre_age += 1
                state.lap_times.append(lap_time)

                history.append({
                    "Lap": lap,
                    "Driver": driver_name,
                    "Team": state.team,
                    "LapTime": round(lap_time, 3),
                    "CumulativeTime": round(state.cumulative_time, 3),
                    "Compound": state.compound,
                    "TyreAge": state.tyre_age,
                    "GridPosition": int(state.grid_position),
                    "Position": 0,  # filled below
                })

            # ---- assign positions after all drivers complete this lap ----
            active = [(d, s.cumulative_time) for d, s in states.items() if not s.retired]
            active.sort(key=lambda x: x[1])  # lowest cumulative time = furthest ahead

            pos_map = {driver: pos + 1 for pos, (driver, _) in enumerate(active)}
            for entry in history:
                if entry["Lap"] == lap:
                    entry["Position"] = pos_map.get(entry["Driver"], 0)
            for driver_name, pos in pos_map.items():
                states[driver_name].position = pos
                states[driver_name].positions.append(pos)

            if lap % 10 == 0 or lap == total_laps:
                leader = active[0][0]
                gap_p2 = active[1][1] - active[0][1] if len(active) > 1 else 0
                print(f"  Lap {lap:3d}/{total_laps}  |  Leader: {leader}  |  Gap to P2: {gap_p2:.3f}s")

        return pd.DataFrame(history)
