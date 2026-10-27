// Mirrors the Pydantic schemas in src/api/app.py exactly — keep these in sync.

export interface Circuit {
  key: string;
  label: string;
}

export interface DriverResult {
  sim_position: number;
  driver: string;
  team: string | null;
  cumulative_time_s: number;
  actual_position: number;
  position_error: number;
  lap_rmse_s: number | null;
}

export interface RaceMetrics {
  mean_position_error: number;
  exact_positions: number;
  within_2_positions: number;
  drivers_compared: number;
  fleet_lap_rmse_s: number | null;
}

export interface RacePrediction {
  circuit: string;
  year: number;
  model: string;
  approach: string;
  in_sample: boolean;
  metrics: RaceMetrics;
  results: DriverResult[];
}

export interface QualDriverResult {
  pred_grid: number;
  driver: string;
  team: string | null;
  predicted_time_s: number;
  actual_time_s: number;
  actual_grid: number;
  grid_error: number;
}

export interface QualMetrics {
  lap_time_rmse_s: number;
  mean_grid_error: number;
  within_2_positions: number;
  exact_positions: number;
  drivers: number;
}

export interface QualifyingPrediction {
  circuit: string;
  year: number;
  model: string;
  approach: string;
  metrics: QualMetrics;
  results: QualDriverResult[];
}

export interface HealthResponse {
  status: string;
  circuits: Circuit[];
  years: number[];
}

export interface LapRecord {
  driver: string;
  team: string;
  time_s: number;
  year: number;
}

export interface LastWinner {
  driver: string;
  team: string;
  year: number;
}

export interface TrackPoint {
  x: number;
  y: number;
}

export interface CornerPoint {
  number: number;
  letter: string | null;
  x: number;
  y: number;
}

export interface TrackMapData {
  outline: TrackPoint[];
  corners: CornerPoint[];
}

export interface ScheduleEvent {
  round: number;
  name: string;
  location: string;
}

export interface SessionDriver {
  code: string;
  name: string;
  team: string;
  driver_id: string;
}

export interface RaceLapRow {
  lap_number: number;
  gap_s: number;
  lap_time_a_s: number;
  lap_time_b_s: number;
  compound_a: string | null;
  compound_b: string | null;
  pit_lap_a: boolean;
  pit_lap_b: boolean;
  track_status: string | null;
  position_a: number | null;
  position_b: number | null;
}

export interface RaceStint {
  stint: number;
  compound: string | null;
  lap_start: number;
  lap_end: number;
  lap_count: number;
  avg_lap_s: number | null;
}

export interface LeadChange {
  lap_number: number;
  gap_s: number;
}

export interface RaceComparison {
  session_id: string;
  driver_a: string;
  driver_b: string;
  laps_compared: number;
  laps_available: number[];
  final_gap_s: number | null;
  lead_changes: LeadChange[];
  stints_a: RaceStint[];
  stints_b: RaceStint[];
  laps: RaceLapRow[];
}

export interface LapSegment {
  corner: number | null;
  start_distance_m: number;
  end_distance_m: number;
  time_delta_s: number;
  braking_point_diff_m: number | null;
  min_speed_diff_kmh: number;
  exit_speed_diff_kmh: number;
  category: "braking" | "apex" | "traction" | "straight-line";
}

export interface TelemetryComparison {
  driver_a: string;
  driver_b: string;
  segment_a: string | null;
  segment_b: string | null;
  position_a: number | null;
  position_b: number | null;
  same_segment: boolean;
  distance_m: number[];
  speed_a: number[];
  speed_b: number[];
  throttle_a: number[];
  throttle_b: number[];
  brake_a: boolean[];
  brake_b: boolean[];
  gear_a: number[];
  gear_b: number[];
  delta_time_s: number[];
  total_delta_s: number;
  segments: LapSegment[];
  insights: string[];
}

export interface CircuitProfile {
  nickname: string;
  tags: string[];
  history: string;
  last_winner: LastWinner | null;
  fastest_race_lap: LapRecord | null;
  fastest_qualifying_lap: LapRecord | null;
  track_map: TrackPoint[] | null;
}
