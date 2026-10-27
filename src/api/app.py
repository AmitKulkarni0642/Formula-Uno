"""
Web layer for the prediction API (FastAPI).

This file only handles HTTP: it defines the endpoints, validates inputs, shapes the
response, and translates errors into HTTP status codes. All the real work lives in
predict_service.py. That separation is the whole point of Stage 1.
"""

from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.api.predict_service import (
    predict_race, predict_qualifying_for, available_circuits, CIRCUITS, SERVE_YEARS,
)
from src.frontend.circuit_profile import get_profile, get_last_winner, get_lap_records, get_track_map
from src.analytics.telemetry_compare import (
    compare_qualifying_laps, get_schedule, get_session_drivers,
    get_track_map as get_track_map_for_year,
)

app = FastAPI(
    title="Formula Uno API",
    version="0.1.0",
    description="Predict F1 race finishing order from a learned lap-time model.",
)

# Allow the local Next.js dev server to call this API directly from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---- Response schemas (Pydantic gives us validation + auto-generated docs) ----

class DriverResult(BaseModel):
    sim_position: int
    driver: str
    team: Optional[str]
    cumulative_time_s: float
    actual_position: int
    position_error: int
    lap_rmse_s: Optional[float]


class Metrics(BaseModel):
    mean_position_error: float
    exact_positions: int
    within_2_positions: int
    drivers_compared: int
    fleet_lap_rmse_s: Optional[float]


class PredictionResponse(BaseModel):
    circuit: str
    year: int
    model: str
    approach: str
    in_sample: bool
    metrics: Metrics
    results: list[DriverResult]


class QualDriverResult(BaseModel):
    pred_grid: int
    driver: str
    team: Optional[str]
    predicted_time_s: float
    actual_time_s: float
    actual_grid: int
    grid_error: int


class QualMetrics(BaseModel):
    lap_time_rmse_s: float
    mean_grid_error: float
    within_2_positions: int
    exact_positions: int
    drivers: int


class QualifyingResponse(BaseModel):
    circuit: str
    year: int
    model: str
    approach: str
    metrics: QualMetrics
    results: list[QualDriverResult]


class LapRecord(BaseModel):
    driver: str
    team: str
    time_s: float
    year: int


class LastWinner(BaseModel):
    driver: str
    team: str
    year: int


class TrackPoint(BaseModel):
    x: float
    y: float


class CircuitProfileResponse(BaseModel):
    nickname: str
    tags: list[str]
    history: str
    last_winner: Optional[LastWinner]
    fastest_race_lap: Optional[LapRecord]
    fastest_qualifying_lap: Optional[LapRecord]
    track_map: Optional[list[TrackPoint]]


class LapSegment(BaseModel):
    corner: Optional[int]
    start_distance_m: float
    end_distance_m: float
    time_delta_s: float
    braking_point_diff_m: Optional[float]
    min_speed_diff_kmh: float
    exit_speed_diff_kmh: float
    category: str


class CornerPoint(BaseModel):
    number: int
    letter: Optional[str]
    x: float
    y: float


class TrackMapResponse(BaseModel):
    outline: list[TrackPoint]
    corners: list[CornerPoint]


class ScheduleEvent(BaseModel):
    round: int
    name: str
    location: str


class SessionDriver(BaseModel):
    code: str
    name: str
    team: str


class TelemetryComparisonResponse(BaseModel):
    driver_a: str
    driver_b: str
    segment_a: Optional[str]
    segment_b: Optional[str]
    position_a: Optional[int]
    position_b: Optional[int]
    same_segment: bool
    distance_m: list[float]
    speed_a: list[float]
    speed_b: list[float]
    throttle_a: list[float]
    throttle_b: list[float]
    brake_a: list[bool]
    brake_b: list[bool]
    gear_a: list[float]
    gear_b: list[float]
    delta_time_s: list[float]
    total_delta_s: float
    segments: list[LapSegment]
    insights: list[str]


# ---- Endpoints ----

@app.get("/health")
def health():
    """Liveness check + what the API can currently serve."""
    return {"status": "ok", "circuits": available_circuits(), "years": SERVE_YEARS}


@app.get("/predict/race", response_model=PredictionResponse)
def predict(
    circuit: str = Query("bahrain", description="Circuit key, e.g. 'bahrain'"),
    year: int = Query(2025, description="Season year to simulate"),
):
    """Simulate a circuit's race for a year and return the predicted finishing order."""
    try:
        return predict_race(circuit, year)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/predict/qualifying", response_model=QualifyingResponse)
def predict_qual(
    circuit: str = Query("bahrain", description="Circuit key, e.g. 'bahrain'"),
    year: int = Query(2025, description="Season year"),
):
    """Predict a circuit's qualifying grid (hybrid: pooled model for data-thin circuits)."""
    try:
        return predict_qualifying_for(circuit, year)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/circuit/profile", response_model=CircuitProfileResponse)
def circuit_profile(circuit: str = Query("bahrain", description="Circuit key, e.g. 'bahrain'")):
    """
    Circuit facts: history/character (static), last winner + lap records (computed
    live from our own cached data), and a real GPS-traced track map where available.
    """
    circuit = circuit.lower()
    if circuit not in CIRCUITS:
        raise HTTPException(status_code=404, detail=f"Unknown circuit '{circuit}'")
    circ = CIRCUITS[circuit]
    profile = get_profile(circuit)
    winner = get_last_winner(circuit, circ["event"], max(SERVE_YEARS))
    records = get_lap_records(circuit, circ["event"], sorted(SERVE_YEARS))
    xy = get_track_map(circ["event"])
    return {
        "nickname": profile["nickname"],
        "tags": profile["tags"],
        "history": profile["history"],
        "last_winner": winner,
        "fastest_race_lap": records["race"],
        "fastest_qualifying_lap": records["quali"],
        "track_map": [{"x": float(x), "y": float(y)} for x, y in zip(*xy)] if xy is not None else None,
    }


@app.get("/schedule", response_model=list[ScheduleEvent])
def schedule(year: int = Query(..., description="Season year, e.g. 2022")):
    """Every Grand Prix on a season's calendar (testing excluded) — for populating a track picker."""
    events = get_schedule(year)
    if not events:
        raise HTTPException(status_code=404, detail=f"No schedule found for {year}.")
    return events


@app.get("/session/drivers", response_model=list[SessionDriver])
def session_drivers(
    year: int = Query(..., description="Season year, e.g. 2022"),
    event: str = Query(..., description="Event name as returned by /schedule, e.g. 'British Grand Prix'"),
):
    """The qualifying roster for one event — only drivers who actually took part."""
    drivers = get_session_drivers(year, event)
    if not drivers:
        raise HTTPException(status_code=404, detail=f"No qualifying roster found for {event} {year}.")
    return drivers


@app.get("/track/map", response_model=TrackMapResponse)
def track_map(
    year: int = Query(..., description="Season year, e.g. 2023"),
    event: str = Query(..., description="Event name as returned by /schedule, e.g. 'Singapore Grand Prix'"),
):
    """
    Real GPS-traced track outline and corner positions for this exact year's
    layout — some circuits (Singapore, Albert Park, ...) have been physically
    reprofiled between seasons.
    """
    result = get_track_map_for_year(year, event)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No track map available for {event} {year}.")
    return {
        "outline": [{"x": x, "y": y} for x, y in result["outline"]],
        "corners": result["corners"],
    }


@app.get("/compare/qualifying", response_model=TelemetryComparisonResponse)
def compare_qualifying(
    event: str = Query(..., description="Event name as returned by /schedule, e.g. 'British Grand Prix'"),
    year: int = Query(..., description="Season year, e.g. 2022"),
    driver_a: str = Query(..., description="First driver's 3-letter code, e.g. 'VER'"),
    driver_b: str = Query(..., description="Second driver's 3-letter code, e.g. 'LEC'"),
):
    """
    Distance-aligned qualifying telemetry comparison for two drivers: speed,
    throttle, brake, gear traces, a delta-time curve, corner-by-corner segment
    breakdown, and templated plain-English insights ranked by time lost/gained.

    Full historical coverage (2018+) requires an authenticated F1 account with an
    active F1TV subscription (see .env / F1_USERNAME, F1_PASSWORD). A 404 here means
    this specific session/driver combo isn't archived, not necessarily a bad request.
    """
    result = compare_qualifying_laps(year, event, driver_a.upper(), driver_b.upper())
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Telemetry not available for {driver_a.upper()}/{driver_b.upper()} "
                   f"at {event} {year} qualifying.",
        )
    return result
