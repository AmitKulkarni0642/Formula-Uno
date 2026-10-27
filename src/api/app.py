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
from src.store import db
from src.store.ingest import ensure_session
from src.compare import loader
from src.compare.service import compare_laps as run_lap_comparison
from src.compare.race import race_pace_comparison

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
    driver_id: str


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


class LapCompareSegment(BaseModel):
    corner: Optional[int]
    start_distance_m: float
    end_distance_m: float
    time_delta_s: float
    braking_point_diff_m: Optional[float]
    min_speed_diff_kmh: float
    throttle_pickup_diff_m: float
    exit_speed_diff_kmh: float
    top_speed_diff_kmh: float
    category: str


class LapCompareMeta(BaseModel):
    session_id: str
    driver_a: str
    lap_a: int
    driver_b: str
    lap_b: int
    sample_rate_hz_approx: int
    caveats: str


class LapCompareResponse(BaseModel):
    meta: LapCompareMeta
    distance_m: list[float]
    speed_a: list[float]
    speed_b: list[float]
    throttle_a: list[float]
    throttle_b: list[float]
    brake_a: list[bool]
    brake_b: list[bool]
    gear_a: list[float]
    gear_b: list[float]
    delta_ms: list[float]
    total_delta_s: float
    segments: list[LapCompareSegment]
    insights: list[str]
    minisector_winners: list[Optional[str]]


class RaceLapComparisonRow(BaseModel):
    lap_number: int
    gap_s: float
    lap_time_a_s: float
    lap_time_b_s: float
    compound_a: Optional[str]
    compound_b: Optional[str]
    pit_lap_a: bool
    pit_lap_b: bool
    track_status: Optional[str]


class RaceStint(BaseModel):
    stint: int
    compound: Optional[str]
    lap_start: int
    lap_end: int
    lap_count: int
    avg_lap_s: Optional[float]


class LeadChange(BaseModel):
    lap_number: int
    gap_s: float


class RaceComparisonResponse(BaseModel):
    session_id: str
    driver_a: str
    driver_b: str
    laps_compared: int
    laps_available: list[int]
    final_gap_s: Optional[float]
    lead_changes: list[LeadChange]
    stints_a: list[RaceStint]
    stints_b: list[RaceStint]
    laps: list[RaceLapComparisonRow]


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
    session_type: str = Query("Q", description="'Q' (qualifying, default) or 'R' (race)"),
):
    """The roster for one event's session — only drivers who actually took part."""
    drivers = get_session_drivers(year, event, session_type)
    if not drivers:
        raise HTTPException(status_code=404, detail=f"No {session_type} roster found for {event} {year}.")
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


@app.get("/compare_laps", response_model=LapCompareResponse)
def compare_laps(
    session_id: str = Query(..., description="e.g. '2024-01-Q' (season-round-code)"),
    driver_a: str = Query(..., description="driver_id slug, e.g. 'max_verstappen' — see /schedule/{year}/{event}/drivers"),
    driver_b: str = Query(..., description="driver_id slug, e.g. 'charles_leclerc'"),
    lap_a: str = Query("fastest", description="'fastest' or a lap number"),
    lap_b: str = Query("fastest", description="'fastest' or a lap number"),
    resolution: int = Query(1, ge=1, le=20, description="Downsample stride for the display channels (1 = full resolution)"),
):
    """
    Phase 2: store-backed lap comparison (any two laps, any driver pair, any
    session already in the processed stats store) — distance-aligned speed/
    throttle/brake/gear traces, a cumulative delta-time curve, corner-by-corner
    segment breakdown, ranked plain-English insights, and mini-sector winners
    for the track map. Distinct from /compare/qualifying (fastest-lap-only,
    live FastF1, pre-dates the store).

    A session not yet in the store (any season 2018-2026) is ingested on
    first request and cached — expect that one call to be noticeably slower.
    """
    con = db.connect()
    try:
        ensure_session(con, session_id, telemetry="fastest")
        return run_lap_comparison(con, session_id, driver_a, lap_a, driver_b, lap_b, resolution)
    except (loader.LapNotFound, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        con.close()


@app.get("/compare_race", response_model=RaceComparisonResponse)
def compare_race(
    session_id: str = Query(..., description="e.g. '2019-12-R' (season-round-code); must be a race (R) session"),
    driver_a: str = Query(..., description="driver_id slug, e.g. 'lewis_hamilton'"),
    driver_b: str = Query(..., description="driver_id slug, e.g. 'max_verstappen'"),
):
    """
    Whole-race, lap-by-lap gap evolution between two drivers — cumulative
    time gap per lap (a broadcast "race trace" chart), pit stops, tyre
    stints, and exactly which laps the on-track order between them flipped.
    This is the "did the tyre offset work" story (e.g. 2019 Hungary: Hamilton's
    extra stop let him close in and pass Verstappen). Lap-level, not telemetry
    — see /compare_laps for a single lap's distance-aligned speed/throttle/brake.

    A session not yet in the store (any season 2018-2026) is ingested on
    first request (laps only, no telemetry — fast) and cached.
    """
    con = db.connect()
    try:
        ensure_session(con, session_id, telemetry="none")
        return race_pace_comparison(con, session_id, driver_a, driver_b)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        con.close()
