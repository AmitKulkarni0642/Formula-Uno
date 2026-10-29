# Formula Uno platform plan

Status: **proposal, awaiting approval.** Nothing in `src/` or `web/` has been changed.
Written 26 October 2026. Deadline: fully deployed by early December 2026 (about 6 weeks).

---

## 0. Blocking finding: F1 timing data now needs an F1TV subscription — RESOLVED 27 Oct 2026

Decision D0 = **A** (F1TV subscription). `F1_USERNAME`/`F1_PASSWORD` set in `.env`, FastF1 confirmed on 3.9.0, full 2018-2026 telemetry verified working end to end (schedule, rosters, track maps, lap telemetry, grid positions). `data/` is now 2.9 GB and growing (2018:106M, 2019:35M, 2021:151M, 2022:1.3G, 2023:202M, 2024:51M, 2025:13M, 2026:219M + 148M models + 656M HTTP cache) — this makes D5 (move off OneDrive) more urgent, not less.

As an ad-hoc prototype ahead of this plan, a telemetry lap-comparison page was already shipped at `web/src/app/compare/page.tsx` — cascading Year/Track/Driver selectors, year-aware SVG track maps with corner labels, grid-position-aware comparison header. It talks to `src/analytics/telemetry_compare.py` directly (no stats store yet) via new endpoints `/schedule`, `/session/drivers`, `/track/map`, and a reshaped `/compare/qualifying` (param renamed `circuit`→`event`, `year` now required). This is real, working Phase 2/3 territory but built outside the Phase 1 store — Phase 1 should subsume it (store-backed telemetry instead of live FastF1 calls per request) rather than duplicate it.

Original finding, for the record (tested 26 October 2026 with a fresh, separate cache; `data/` was not touched at the time):

| Source | Result |
|---|---|
| F1 live-timing service used by FastF1 3.8.3 (installed) | **HTTP 401 Unauthorized** for every file, every season, including 2018, 2022, 2025 and 2026. FastF1 loads fail with "Failed to load timing data" and "Car telemetry data is unavailable". |
| FastF1 3.9.0 (latest, tested in a throwaway venv) | Adds `python -m fastf1 auth f1tv --authenticate`. Its own error text: "An active F1TV subscription is required." |
| OpenF1 API (free, no auth for historical data) | Works. 2023-2026 sessions (2026 calendar to Abu Dhabi on 5 Dec). `car_data` at about 4 Hz (speed, throttle, brake, gear, rpm, DRS), `location` (x, y, z), `laps` (sectors, speed traps, mini-sector segments), `stints` (compound, tyre age). **No data before 2023.** |
| Jolpica (Ergast successor) | Works for 2018-2026: results, qualifying, lap times, pit stops. **No telemetry, no tyre compounds.** |

Your existing project still works only because its cache was downloaded before this change (latest files 12 October). Anything not already cached cannot be fetched with the current setup.

**Consequence for the brief.** "Every season 2018-2026, telemetry comparisons for any event" is only possible with an F1TV subscription. Without one, telemetry is limited to 2023-2026 (OpenF1) plus the 10 circuits of 2022 already in your cache; 2018-2022 would have results and lap times only.

**Options (decision D0)**

| Option | Coverage | Cost / risk |
|---|---|---|
| A. F1TV subscription + upgrade to FastF1 3.9.0 | Full 2018-2026, one source | Subscription cost; the token expires and needs re-auth; the deployed server needs a token to ingest new rounds (or ingest locally and upload). F1TV terms may restrict publicly redistributing derived timing data, so check before a public deployment. |
| B. No subscription: OpenF1 2023-2026 + Jolpica 2018-2022 + existing 2022 cache | Telemetry 2023-2026 only; laps/results 2018-2026; no tyre data before 2023 | Free. Two sources mapped into one schema. Telemetry pages show "not available for this season" before 2023. Era 2018-21 backtests limited to results-based features. |
| C. A for the historical backfill, OpenF1 for new 2026 rounds in production | Full coverage | Same as A, but the deployed server never needs F1TV credentials. |

Recommendation: **C** if you have or are willing to get F1TV; otherwise **B** with the coverage limits stated plainly in the UI. Either way, Phase 1 is built with source adapters writing to one schema, so the choice can change later without touching anything downstream.

---

## 1. What exists today

| Area | What is there | Notes |
|---|---|---|
| Ingestion | `src/ingestion/load_session.py`: FastF1 race and qualifying loads with per-lap weather. FastF1 cache in `data/` (481 MB HTTP cache + per-session pickles). | `telemetry=False` everywhere except the track-map helper. Only race (R) and qualifying (Q) are loaded; no practice or sprint sessions. |
| Data on disk | 10 circuits x 2022-2025. | Only 2022 sessions hold car/position telemetry (887 MB). 2023-2025 hold timing only. |
| Features | `src/features/build_features.py`: 12 features (LabelEncoded driver/team/track, `YearEncoded = year - 2022`, lap, compound, tyre life and its square, linear fuel, grid position, track/air temp). Wet, SC/VSC, deleted and inaccurate laps dropped. | LabelEncoders fail on unseen drivers/teams (2026 rookies, Cadillac, Audi). `YearEncoded` goes negative before 2022. No era feature. |
| Models | XGBoost lap-time regressors, one race and one quali model per circuit plus pooled 8- and 10-circuit models, trained on 2022-2024. Pickled in `data/models/` (148 MB). | Validation is random 5-fold CV over laps, so laps from the same race land in train and test. |
| Race engine | `src/engine/race_engine.py`: deterministic lap-by-lap simulation; positions from sorted cumulative time. | **Replays the real race's pit laps, compounds and actual in/out-lap times, and the real grid.** No DNFs (`retired` is never set), no SC, no overtaking cost. It reconstructs a known race; it cannot forecast one. |
| Quali "prediction" | `src/analytics/qualifying.py` | Uses each driver's actual best quali lap (compound, tyre age, temps) and race `GridPosition`, which is essentially the quali result. Same issue: a reconstruction, not a forecast. |
| Analytics | `compare.py` (sim vs actual), `development.py` (season gap-to-pole + change-point detection), pit-window helper in `predict_service.py`. | Useful pieces to keep. |
| API | FastAPI `src/api/app.py`: `GET /health`, `GET /predict/race`, `GET /predict/qualifying`, `GET /circuit/profile`. In-process dict caches. CORS: localhost:3000, GET only. | Circuit/year whitelist: 10 circuits, 2022-2025. |
| Frontends | Streamlit app `src/frontend/streamlit_app.py` (369 lines). Next.js 16.4 + React 19.3 + Tailwind 4 + Motion in `web/` (one client-side page, 3 components), its own git repo with uncommitted changes. | `src/api/app.py` imports `src/frontend/circuit_profile.py`. |
| Tests | None. | |
| Version control | The project root is **not** a git repository. Only `web/` is. | |
| Environment | Python 3.14.4, FastF1 3.8.3, FastAPI 0.128, XGBoost 3.3, pandas 2.3, pyarrow 26, pytest 9 installed. Not installed: DuckDB. | Project lives in OneDrive. |

---

## 2. Conflicts with the brief (flagged, not guessed)

1. **Existing predictions are reconstructions.** `/predict/race` and `/predict/qualifying` use information from the session they "predict". They stay untouched (no breaking changes) but the UI must label them as replays or "model reconstruction", never as forecasts. Real forecasts come from new Phase 4 endpoints.
2. **The current model interface cannot serve 2018-2026, any event.** Per-circuit models, LabelEncoded identities and `year - 2022` cannot handle 24 circuits a year, new teams, or eras. Phase 4 needs a new global model. This is a **model architecture change and needs your approval** (decision D1). The old models and endpoints keep working unchanged.
3. **Endpoint names.** The brief's `/predict_race` and `/predict_quali` sit next to existing `/predict/race` and `/predict/qualifying`. I will add the new ones with your exact names and leave the old ones alone, documented as "historical reconstruction". Decision D2 confirms this.
4. **"No Streamlit anywhere".** The Streamlit app and `python run.py frontend` exist today. Plan: move `circuit_profile.py` (not Streamlit-specific, used by the API) to `src/analytics/`, leave a re-export shim at the old path, and delete the Streamlit app once the Next.js app reaches parity. Deleting needs your OK (D3).
5. **No git at the project root.** Before any change I want to `git init` the root (keeping `web/` as is or folding it in, D4), commit the current state as a baseline, and work on a branch. Without this there is no safe rollback.
6. **OneDrive.** A 2018-2026 telemetry cache will be tens of GB. OneDrive will try to sync it, and the Next.js log already shows Turbopack stalling on OneDrive-synced `node_modules`. Recommendation: put the FastF1 cache and the stats store outside OneDrive via an env var (for example `C:\f1data`) (D5).
7. **Heavy dependencies to approve** (D6): `duckdb` (Python), `apache-echarts` + `echarts-for-react` or `uplot` (web), shadcn/ui components (copied source, Radix deps), `openapi-typescript` + `openapi-fetch` (typed client), an LLM SDK for chat, and a small embedding/vector option for RAG.

---

## 3. Cross-cutting design

### One ID scheme

| Entity | ID | Example |
|---|---|---|
| Event | `{season}-{round:02d}` | `2026-18` |
| Session | `{event_id}-{code}`, code in FP1, FP2, FP3, SQ, S, Q, R | `2026-18-Q` |
| Driver | Ergast/Jolpica `DriverId` from FastF1 results (stable across numbers and teams) | `max_verstappen` |
| Team | `TeamId` from FastF1 results, plus a `lineage_id` for renames (Toro Rosso to AlphaTauri to RB; Sauber/Alfa Romeo to Audi) | `red_bull` |
| Lap | `(session_id, driver_id, lap_number)` | |
| Circuit | `circuit_key` from FastF1 event `Location`, normalised | `monza` |

### Regulation era

`era` column on events: `2018-21` (pre ground effect), `2022-25` (ground effect), `2026+`. Used as a model feature, a backtest breakdown and a UI badge.

### Config

One `settings.py` (pydantic-settings): `F1_CACHE_DIR`, `STORE_DIR`, `CORS_ORIGINS`, `LLM_API_KEY`, `ENV`. No hard-coded paths.

---

## 4. Phase 1: processed stats store

**Files**

- `src/store/schema.sql`: DuckDB tables (below).
- `src/store/db.py`: connection, upserts, read helpers.
- `src/store/ingest.py`: `python -m src.store.ingest --season 2024 [--event 5] [--sessions Q,R] [--telemetry fastest|none] [--source auto|fastf1|openf1|jolpica] [--force]`.
- `src/store/sources/`: one adapter per source (`fastf1_src.py`, `openf1_src.py`, `jolpica_src.py`), each returning the same normalised frames. `sessions.source` records where every row came from.
- `src/store/ids.py`: ID helpers and team lineage map.
- `tests/test_ingest_ids.py`, `tests/test_store_idempotent.py`.

**Storage.** One DuckDB file for relational tables plus Parquet partitions (`telemetry/season=2024/event=05/session=Q/*.parquet`) for the large telemetry table. DuckDB queries Parquet directly, so there is still one query surface.

**Tables (minimum)**

| Table | Key columns |
|---|---|
| `events` | event_id, season, round, name, circuit_key, country, date, era, format (conventional/sprint) |
| `sessions` | session_id, event_id, code, start_utc, has_telemetry, ingested_at, fastf1_version, status |
| `drivers`, `teams` | driver_id, abbreviation, full_name; team_id, name, color, lineage_id |
| `entries` | session_id, driver_id, team_id, car_number |
| `results` | session_id, driver_id, position, grid, status, points, q1_ms, q2_ms, q3_ms |
| `laps` | session_id, driver_id, lap_number, lap_ms, s1_ms, s2_ms, s3_ms, compound, stint, tyre_life, fresh_tyre, pit_in, pit_out, track_status, is_deleted, deleted_reason, is_accurate, position, session_time_ms, air_temp, track_temp, rainfall |
| `minisectors` | session_id, driver_id, lap_number, ms_index (25 equal-distance segments), time_ms (fastest laps) |
| `telemetry` (Parquet) | session_id, driver_id, lap_number, sample_idx, t_ms, distance_m, speed, throttle, brake, gear, rpm, drs, x, y (native samples, fastest lap per driver per session) |
| `track_outline` | circuit_key, season, idx, x, y, distance_m (one reference lap, for maps) |
| `corners` | circuit_key, season, number, letter, distance_m, x, y, angle (from `get_circuit_info()`) |
| `ingest_log` | session_id, step, status, rows, finished_at, error |

**Idempotency.** Every write is `DELETE WHERE session_id = ?` then insert, inside a transaction; `ingest_log` makes reruns skip completed steps unless `--force`. Partial failures leave the session marked `failed`, never half-written.

**Volume estimate (to confirm in the first backfill).** About 9 seasons x 22 events x 5-6 sessions. Laps: about 1-1.5 M rows. Fastest-lap telemetry: about 20 drivers x 6 sessions x 200 events x ~800 samples = about 20 M rows, roughly 1-2 GB Parquet. The FastF1 raw cache will be far larger (tens of GB) and stays local, never deployed.

**Any-lap telemetry.** Phase 2 compares *any* two laps, but storing every lap's telemetry is too large. Non-fastest laps are fetched on demand from FastF1, resampled, and written back to the same Parquet table (lazy cache).

---

## 5. Phase 2: lap comparison engine

**Files**: `src/compare/align.py`, `src/compare/segments.py`, `src/compare/insights.py`, `tests/test_align.py`, `tests/test_segments.py`.

**Method**

1. Distance: use FastF1's integrated `Distance`, then rescale each lap so it ends at the reference lap length (removes 0.5-1 % drift from integrating ~4 Hz speed).
2. Resample both laps to a 1 m grid by linear interpolation of time, speed, throttle, gear; brake stays boolean (nearest sample).
3. Delta: `delta(d) = t_B(d) - t_A(d)`, cumulative by construction.
4. Segmentation: around each corner from `corners`, find the apex as minimum speed within a window; braking zone = first brake-on (or speed-drop > threshold when brake is noisy) before the apex; entry = brake release to apex; exit/traction = apex to throttle >= 95 %; the rest is straight.
5. Per segment: time delta (difference of delta at segment ends), braking point diff (m, **flagged approximate**: with ~4 Hz samples at 300 km/h one sample spans ~20 m), min speed diff, throttle pickup diff (m), exit speed diff, top speed diff.
6. Classification: each loss attributed to braking / apex / traction / straight by which segment it occurs in, plus the dominant metric. Insights: ranked by time lost, templated plain English with numbers (no LLM).

**Endpoint**

`GET /compare_laps?session_id=2026-18-Q&driver_a=norris&lap_a=fastest&driver_b=piastri&lap_b=fastest&resolution=5`

Returns: meta (laps, times, sample rate, caveats), downsampled channels for display, delta curve, segments table, ranked insights, mini-sector winners for the track map.

**Tests**: synthetic laps with known offsets (constant speed difference gives a linear delta; a shifted braking point is recovered within one grid step), monotonic distance, segment boundaries cover the lap without gaps.

---

## 6. Phase 3: web app

Stack as specified (Next.js App Router, TypeScript, Tailwind, shadcn/ui, Framer Motion/`motion`, ECharts for dense charts). Built inside the existing `web/` project. **Note:** `web/AGENTS.md` warns this Next.js 16.4 has breaking changes; I will read its bundled docs before writing code.

**Before building:** two design directions (palette, display/UI/mono fonts, spacing, surfaces, motion) for you to pick. Not started.

**Routes (every view shareable by URL)**

```
/                                   current season landing
/[season]                           season page: calendar, standings, title odds
/[season]/[round]                   event page, default tab
/[season]/[round]/preview           forecasts
/[season]/[round]/quali             telemetry analysis (?a=norris&b=piastri&la=fastest&lb=fastest)
/[season]/[round]/race              lap-by-lap, head-to-head (?h2h=a,b)
/[season]/[round]/review            predicted vs actual
/drivers/[driverId]                 driver page
```

Typed client generated from FastAPI's OpenAPI schema (`openapi-typescript`), one chart theme module, one design token file.

**Per-page loop:** run, screenshot, critique against the design bar, polish pass, then move on.

---

## 7. Phase 4: forecasts

**New global model (needs approval, D1).** One race lap-time model and one quali model across all circuits and 2018-2026, replacing label-encoded identities with:

- rolling team pace: team's median clean-lap gap to the session's fastest, exponentially weighted over recent events, with 2026 data up-weighted (sample weights by era and recency);
- rolling driver-vs-teammate gap;
- track features: power sensitivity, overtaking difficulty, degradation severity (computed from the store);
- era, compound, tyre life, fuel, temperatures, session stage.

**Superseded 29 Oct 2026 (new decision, D1-b):** XGBoost is being replaced, not kept. User's call, having seen the tradeoffs (LightGBM/CatBoost stay in the tree-ensemble family and inherit XGBoost's inability to extrapolate past training ranges; a probabilistic GBM mitigates but doesn't escape it) — a tabular MLP (PyTorch) instead, the only option that doesn't inherit trees' extrapolation ceiling. Higher lift (needs real scaling/regularization/training-loop work, more overfitting risk at this dataset size) but that's the explicit tradeoff being made. See `src/forecast/nn_model.py`, `src/forecast/train_nn.py`.

**Monte Carlo race simulator (`src/forecast/montecarlo.py`)**: vectorised NumPy, not per-lap `model.predict` (the current engine calls predict per driver per lap, which would take hours for thousands of runs). Precompute each driver's pace curve over compound x tyre age x fuel once, then simulate N=5,000 races with stochastic SC/VSC (per-track historical rates), pit timing from a strategy model, DNFs (per-team reliability prior), start-position effects and an overtaking cost from the track feature. Outputs: win/podium/points probabilities, expected position, stop count and pit windows. Two stages: post-practice and post-quali.

**Endpoints**: `GET /predict_quali?event_id=&stage=`, `GET /predict_race?event_id=&stage=post_practice|post_quali&n_sims=`, `GET /backtest_results?kind=&era=`, later `/championship_odds`, `/what_if`.

**Backtests (`src/forecast/backtest.py`)**: walk-forward by round, never training on the event being predicted or later. Report winner accuracy, podium hit rate, Spearman, by era. Tests on split construction.

**Persisted predictions**: `predictions(prediction_id, kind, event_id, stage, created_at, session_start_utc, model_version, inputs_hash, payload)`; a prediction counts as verifiable only if `created_at < session_start_utc`. Needs a scheduled job in deployment.

**Cut line if short on time**: championship simulator and what-if go first.

---

## 8. Phase 5: chat

Agent with tools that read the store: `fastest_drivers(season, metric)`, `sector_breakdown(event, session, driver)`, `compare_laps(...)`, `race_pace_summary(event)`, `predict_race(event)`. "Fastest" always states its metric. RAG only over a small curated corpus (regulations summary, track notes). SSE streaming endpoint `POST /chat`. Page context (season, event, session, drivers) sent with every message. Tool results rendered with the shared chart/table components. Provider and model: decision D7.

---

## 9. Deployment

Frontend on Vercel. Backend Docker image (FastAPI + read-only DuckDB/Parquet store) on Fly.io or Railway with a persistent volume; the store is built locally by ingestion and uploaded (or rebuilt on the server by a scheduled job for new 2026 rounds). Env-based config and CORS for the Vercel domain. README with setup and deploy steps. Risk: free tiers have 512 MB-1 GB RAM; XGBoost + DuckDB + Monte Carlo may need a paid tier (~$5-10/month).

---

## 10. Timeline (6 weeks)

| Week | Dates | Work |
|---|---|---|
| 1 | 27 Oct - 2 Nov | Git baseline, config, Phase 1 store + backfill 2018-2026 |
| 2 | 3 - 9 Nov | Phase 2 comparison engine; design directions for Phase 3 |
| 3 | 10 - 16 Nov | Phase 3 shell, event page Quali/Race tabs; first backend deploy |
| 4 | 17 - 23 Nov | Phase 4 model + Monte Carlo + backtests; Preview/Review tabs |
| 5 | 24 - 30 Nov | Phase 5 chat; driver and season pages |
| 6 | 1 - 5 Dec | Hardening, Lighthouse, deploy, README; cut items if needed |

This is tight for the full brief. The plan front-loads the foundation so later cuts (championship sim, what-if, RAG depth) don't block a working deployment.

---

## 11. Decisions needed

| ID | Decision | Recommendation |
|---|---|---|
| D0 | Data source: F1TV subscription (A), free sources with reduced coverage (B), or both (C). See section 0. Upgrading FastF1 to 3.9.0 is part of A and C. | C if you have F1TV, else B |
| D1 | Approve a new global forecasting model (features change, XGBoost stays). Old models untouched. | Yes |
| D2 | New endpoints use your exact names alongside the old `/predict/*`, which are relabelled as reconstructions. | Yes |
| D3 | Delete the Streamlit app once the web app reaches parity. | Yes |
| D4 | `git init` the project root and commit a baseline first. Fold `web/` into it (drop its separate `.git`) or keep it separate. | Init now; fold `web/` in |
| D5 | Move the FastF1 cache and store outside OneDrive. | Yes, e.g. `C:\f1data` |
| D6 | Approve dependencies: duckdb, ECharts, shadcn/ui, openapi-typescript/openapi-fetch, LLM SDK, small RAG store. | Yes |
| D7 | Chat LLM provider and model, and who holds the API key. | Anthropic Claude via your key |
| D8 | Backend host: Fly.io, Railway or Render. | Fly.io (volumes, Docker-native) |
