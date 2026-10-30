# Project structure

A file-by-file map of the repo. For *why* things are built this way, see
[`PLAN.md`](PLAN.md) (design decisions) and [`PROGRESS.md`](PROGRESS.md)
(build log, phase by phase). This file is just "what's where."

```
Formula Uno/
├── run.py                  Single CLI entry point — list / train / train-all / predict / benchmark / api
├── run_austria.py )
├── run_bahrain.py ) legacy, superseded by run.py — kept for reference in archive/
├── run_spa.py      )
├── run_multi_circuit.py )
├── run_benchmark.py      )
├── run_api.py             )
├── HOW_TO_RUN.md           Quick-start walkthrough for the old reconstruction engine (run.py)
├── README.md               Project overview, setup, how to run both engines
├── PLAN.md                 Full platform redesign plan — decisions, options, rationale
├── PROGRESS.md             Phase-by-phase build log: what was built, bugs found/fixed, results
├── requirements.txt        Python dependencies
├── archive/                Superseded one-off scripts, kept for history, not imported by anything live
├── notebooks/              Scratch Jupyter notebooks (empty / exploratory)
├── data/                   Local-only: FastF1 cache, DuckDB store, model artifacts — gitignored
│
├── src/
│   ├── settings.py          Single source of truth for paths/env (.env-backed): cache dir, store dir,
│   │                        model dir, CORS origins, F1TV credentials (checked for truthiness only)
│   ├── pipeline.py          Old engine: run_circuit() / run_multi_circuit() — train + evaluate one or
│   │                        several circuits end to end (used by run.py's train/train-all/predict)
│   │
│   ├── ingestion/
│   │   └── load_session.py       FastF1 race/qualifying session loading, with per-lap weather
│   │
│   ├── store/                    Phase 1: processed stats store (DuckDB + Parquet), source of truth
│   │   ├── db.py                   DuckDB connection + idempotent DELETE-then-INSERT writes
│   │   ├── ids.py                  Stable IDs across seasons: event/session/driver/team + team
│   │   │                           lineage mapping (Sauber→Audi, Toro Rosso→RB, etc.), era buckets
│   │   ├── ingest.py                CLI: `python -m src.store.ingest --season Y [--event N]` — backfill
│   │   ├── schema.sql               DuckDB table definitions
│   │   └── sources/
│   │       └── fastf1_src.py          FastF1-backed source adapter feeding the store
│   │
│   ├── features/
│   │   └── build_features.py      Old engine's feature table: LabelEncoded driver/team/track,
│   │                               compound/tyre-life/fuel/temp features, per-circuit, 2022+ only
│   │
│   ├── model/                    Old engine: per-circuit XGBoost
│   │   ├── train.py                 Train + save/load a lap-time regressor (XGBoost), feature importance
│   │   └── benchmark.py             Cross-validated comparison of candidate model families
│   │
│   ├── engine/
│   │   └── race_engine.py         Old engine: deterministic lap-by-lap race RECONSTRUCTION — replays
│   │                               the real race's actual pit laps/compounds/grid, not a forecast
│   │
│   ├── analytics/
│   │   ├── compare.py               Simulated-vs-actual finishing order comparison
│   │   ├── development.py           Season-long qualifying-pace-vs-pole trend + change-point detection
│   │   ├── qualifying.py            Old engine's qualifying "prediction" (reconstruction, same caveat
│   │   │                            as race_engine.py — uses the real grid position as a feature)
│   │   └── telemetry_compare.py     Real FastF1 telemetry comparison between two drivers' fastest laps
│   │
│   ├── compare/                  Phase 2: store-backed lap/race comparison engine behind /compare_*
│   │   ├── align.py                 Distance-aligns two laps point-for-point (corrects FastF1 drift)
│   │   ├── segments.py              Splits an aligned lap pair into per-corner time-gain/loss segments
│   │   ├── insights.py              Plain-English ranked summary of where time was gained/lost
│   │   ├── loader.py                Resolves "driver + lap spec" to telemetry (store, else live FastF1)
│   │   ├── race.py                  Whole-race cumulative gap evolution, positions, pit stops, strategy
│   │   └── service.py               Orchestrates one /compare_laps request end to end
│   │
│   ├── forecast/                 Phase 4: NEW global forecast engine (replaces per-circuit XGBoost)
│   │   ├── schedule.py              Chronological event calendar (season/round), independent of the
│   │   │                            store's partial backfill
│   │   ├── pace.py                  Leakage-safe rolling team/driver pace features (shift(1)-EWM, "as of")
│   │   ├── track_features.py        Circuit fingerprint: typical lap time, power sensitivity, tyre
│   │   │                            degradation slope, overtaking/position-change rate
│   │   ├── features.py              Builds the global per-lap (race) / per-best-lap (quali) training
│   │   │                            frame: continuous + categorical (compound/era) columns, target
│   │   ├── nn_model.py              LapTimeNet — PyTorch tabular MLP (embeddings for compound/era,
│   │   │                            Linear→BatchNorm→GELU→Dropout trunk)
│   │   ├── train_nn.py              Training loop: event-level holdout split, target standardization,
│   │   │                            early stopping. CLI: `python -m src.forecast.train_nn ...`
│   │   ├── infer.py                 Loads a trained model artifact and runs inference on new rows
│   │   ├── weather.py               Forecasts a future session's weather: Open-Meteo air-temp forecast
│   │   │                            + circuit-specific historical air→track temp offset
│   │   ├── live.py                  "Current form" snapshot for an event with no data yet (roster,
│   │   │                            pace, track stats, as of right now)
│   │   ├── montecarlo.py            Monte Carlo race simulator: stop-count distribution, DNF rates,
│   │   │                            safety-car probability (shrunk toward a pooled rate), pit loss,
│   │   │                            lap-to-lap noise — all measured from real historical data
│   │   └── forecast_event.py        Orchestrator: ties everything above into one forecast_event() call
│   │                                — predicted grid + N-trial Monte Carlo race forecast for a future event
│   │
│   ├── api/
│   │   ├── app.py                   FastAPI app: /health, /predict/race, /predict/qualifying (old
│   │   │                            reconstruction engine), /circuit/profile, /schedule, /session/drivers,
│   │   │                            /track/map, /compare/qualifying, /compare_laps, /compare_race
│   │   └── predict_service.py       Compute layer behind the old /predict/* endpoints (load artifacts,
│   │                                simulate, return a plain dict — kept separate from the web layer)
│   │
│   └── frontend/                 Legacy Streamlit app — superseded by web/, slated for removal (PLAN.md D3)
│       ├── streamlit_app.py
│       └── circuit_profile.py       Still imported by src/api/app.py — not Streamlit-specific
│
├── tests/                   pytest suite — all offline/synthetic, no network calls
│   ├── test_forecast_pace.py, test_forecast_track_features.py, test_forecast_live.py,
│   │   test_forecast_weather.py, test_forecast_montecarlo.py    Phase 4 forecast-engine correctness
│   ├── test_align.py, test_segments.py, test_race.py             Phase 2 compare-engine correctness
│   └── test_ingest_ids.py, test_store_idempotent.py,
│       test_store_telemetry_naming.py                            Phase 1 store correctness
│
└── web/                     Next.js 16 / React 19 / Tailwind 4 / ECharts frontend
    └── src/
        ├── app/
        │   ├── page.tsx              Landing page
        │   ├── [season]/page.tsx     Season/event browser
        │   ├── compare/page.tsx      Telemetry lap-comparison page (cascading Year/Track/Driver)
        │   └── layout.tsx, globals.css
        ├── components/
        │   ├── NavBar.tsx
        │   ├── CircuitProfileCard.tsx
        │   ├── PredictionViews.tsx      Renders old-engine predictions, labelled as reconstructions
        │   ├── RaceCompareChart.tsx
        │   ├── TelemetryCompareChart.tsx
        │   └── TrackMap.tsx             Year-aware SVG track map with corner labels
        └── lib/
            ├── api.ts                   Typed fetch wrappers around the FastAPI backend
            ├── types.ts                 Shared TypeScript types mirroring the API's Pydantic models
            ├── circuitLookup.ts
            └── format.ts
```

---

## The two engines, at a glance

| | Old (reconstruction) | New (forecast) |
|---|---|---|
| Location | `src/features/`, `src/model/`, `src/engine/`, `src/analytics/qualifying.py` | `src/forecast/` |
| Scope | One XGBoost model per circuit | One PyTorch model, global across circuits/eras |
| Input for a "prediction" | The real session's own data (actual pit laps, actual grid) | Only data from *before* the event (rolling as-of features) |
| Output | One deterministic lap-time/position guess | A probability distribution (Monte Carlo over 5,000 trials) |
| Endpoints | `/predict/race`, `/predict/qualifying` | Not yet exposed via API (`forecast_event()` callable directly) |
| Status | Frozen, kept working, clearly labelled as a replay | Active development |

## Things not to confuse

- **`src/analytics/qualifying.py`** (old, reconstruction) vs. **`src/forecast/forecast_event.py`**'s
  `predict_grid()` (new, genuine forecast) — same stated goal, opposite data discipline.
- **`src/frontend/`** (Streamlit, legacy) vs. **`web/`** (Next.js, active) — only `web/` is maintained.
- **`archive/`** vs. **root `run_*.py` scripts that were just moved there** — both are dead code kept
  for history; nothing in `src/` imports from `archive/`.
