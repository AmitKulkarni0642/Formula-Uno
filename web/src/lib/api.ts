import type {
  CircuitProfile, HealthResponse, QualifyingPrediction, RacePrediction, TelemetryComparison,
  ScheduleEvent, SessionDriver, TrackMapData, RaceComparison,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `Request failed (${res.status})`, res.status);
  }
  return res.json();
}

export function getHealth(): Promise<HealthResponse> {
  return getJSON("/health");
}

export function getRacePrediction(circuit: string, year: number): Promise<RacePrediction> {
  return getJSON(`/predict/race?circuit=${circuit}&year=${year}`);
}

export function getQualifyingPrediction(circuit: string, year: number): Promise<QualifyingPrediction> {
  return getJSON(`/predict/qualifying?circuit=${circuit}&year=${year}`);
}

export function getCircuitProfile(circuit: string): Promise<CircuitProfile> {
  return getJSON(`/circuit/profile?circuit=${circuit}`);
}

export function getQualifyingComparison(
  event: string,
  year: number,
  driverA: string,
  driverB: string
): Promise<TelemetryComparison> {
  return getJSON(
    `/compare/qualifying?event=${encodeURIComponent(event)}&year=${year}&driver_a=${driverA}&driver_b=${driverB}`
  );
}

export function getSchedule(year: number): Promise<ScheduleEvent[]> {
  return getJSON(`/schedule?year=${year}`);
}

export function getSessionDrivers(
  year: number,
  event: string,
  sessionType: "Q" | "R" = "Q"
): Promise<SessionDriver[]> {
  return getJSON(
    `/session/drivers?year=${year}&event=${encodeURIComponent(event)}&session_type=${sessionType}`
  );
}

export function getTrackMapForYear(year: number, event: string): Promise<TrackMapData> {
  return getJSON(`/track/map?year=${year}&event=${encodeURIComponent(event)}`);
}

// sessionId looks like "2026-07-R" (season-round-code) — see src/store/ids.py.
// A race not yet in the backend's store is ingested on first request (laps
// only, no telemetry), so this specific call can take ~15-30s the first time.
export function getRaceComparison(
  sessionId: string,
  driverA: string,
  driverB: string
): Promise<RaceComparison> {
  return getJSON(
    `/compare_race?session_id=${encodeURIComponent(sessionId)}&driver_a=${driverA}&driver_b=${driverB}`
  );
}

export { ApiError };
