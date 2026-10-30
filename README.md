# Formula Uno

An F1 analytics and prediction platform: a FastAPI backend (FastF1-sourced data,
DuckDB/Parquet stats store, PyTorch forecasting models, Monte Carlo race
simulation) behind a Next.js frontend.

The project has two generations of "prediction" living side by side, and they
are not the same thing:

- **Reconstruction engine** (`/predict/race`, `/predict/qualifying`) — the
  original per-circuit XGBoost models. They use information from the session
  they're "predicting" (real pit laps, real grid position), so they replay a
  known race rather than forecast an unknown one. Kept working, clearly
  labelled, not removed.
- **Forecast engine** (`src/forecast/`) — a global PyTorch model trained once
  across every circuit/era, plus a Monte Carlo race simulator. This is a
  genuine forecast: for a future event it only ever sees data from before that
  event (rolling "as-of" features, no leakage), and it outputs a probability
  distribution over finishing order, not a single deterministic guess.

See [`PLAN.md`](PLAN.md) and [`PROGRESS.md`](PROGRESS.md) for the full design
history and a phase-by-phase log of what was built, why, and what broke along
the way.

---

## Stack

| Layer | Tech |
|---|---|
| Data source | [FastF1](https://docs.fastf1.dev/) 3.9 (requires an F1TV subscription for full 2018-2026 telemetry) |
| Processed store | DuckDB + Parquet |
| Reconstruction models | XGBoost (per-circuit) |
| Forecast model | PyTorch tabular MLP, trained globally across circuits/eras |
| Race simulation | Vectorized NumPy Monte Carlo |
| Weather forecasting | Open-Meteo (free, no key) + circuit-specific historical offset |
| API | FastAPI |
| Frontend | Next.js 16 / React 19 / Tailwind 4 / ECharts |

---

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root (never commit this):

```
F1_USERNAME=your_f1tv_email
F1_PASSWORD=your_f1tv_password
F1_CACHE_DIR=C:\f1data           # optional override, keeps the FastF1 cache off OneDrive
STORE_DIR=C:\f1data\store        # optional
MODEL_DIR=C:\f1data\models       # optional
```

`F1_USERNAME`/`F1_PASSWORD` are only checked for truthiness, never logged. Without
an F1TV subscription, FastF1 3.9 cannot fetch full historical telemetry — see
`PLAN.md` section 0 for the documented fallback (OpenF1 + Jolpica, reduced
coverage before 2023).

For the frontend:

```bash
cd web
npm install
```

---

## Running it

Everything backend-side goes through `run.py`:

```bash
python run.py list                      # circuits/examples available to the old engine
python run.py train-all                  # train the old per-circuit XGBoost models
python run.py predict bahrain 2025       # reconstruction demo
python run.py benchmark                  # compare model families on the same data
python run.py api                        # start the FastAPI server (:8000, /docs for Swagger)
```

Forecast engine (new global model), via its own CLI entry points:

```bash
python -m src.forecast.train_nn --session-type R --train-seasons 2022 2023 2024
python -m src.forecast.train_nn --session-type Q --train-seasons 2022 2023 2024
python -m src.forecast.forecast_event --season 2026 --round 19   # live Mexico City GP forecast
```

Frontend:

```bash
cd web
npm run dev          # http://localhost:3000
```

---

## Testing

```bash
pytest
```

All tests are synthetic/offline (no network calls) — they check the math
(leakage-safe rolling features, Monte Carlo correctness, shrinkage statistics,
weather-combination logic) in isolation from FastF1 or any live API.

---

## Project layout

```
src/
  ingestion/     FastF1 session loading (race + qualifying, per-lap weather)
  store/         DuckDB + Parquet processed stats store, ID/lineage mapping
  features/      Feature engineering for the old per-circuit models
  model/         XGBoost training + benchmarking (old reconstruction engine)
  engine/        Deterministic race-replay engine (old reconstruction engine)
  analytics/     Comparison, qualifying, development, telemetry analytics
  compare/       Lap/race comparison service
  forecast/      New global forecast engine: pace/track rolling features,
                 PyTorch MLP, weather forecasting, live snapshots, Monte
                 Carlo race simulation, end-to-end event orchestration
  api/           FastAPI app exposing both engines
web/             Next.js frontend
tests/           pytest suite (offline/synthetic)
```

---

## Status

Phase 4 (replacing the per-circuit XGBoost reconstruction with a global,
genuinely-forecasting model) is complete for both halves of its scope:

1. **Validation** — trained on 2022-2024, evaluated on held-out 2025: race
   RMSE 3.45s / MAE 2.85s, qualifying RMSE 4.57s / MAE 3.24s — in the same
   range as the old per-circuit specialists, despite one model now covering
   every circuit and era instead of ten.
2. **Live forecasting** — an end-to-end forecast for an upcoming event (grid
   prediction + 5,000-trial Monte Carlo race simulation, using real
   historical strategy/DNF/safety-car statistics and a genuine weather
   forecast rather than recorded data), verified against the upcoming Mexico
   City GP.

Known, named simplifications (not hidden): pit strategy/compound choice is a
fixed heuristic rather than a learned model; qualifying-gap spread looks
narrower than typical real-world variance; each live forecast call currently
re-sweeps historical data independently rather than sharing one load pass,
so it's slow (dominated by a flaky third-party API FastF1 falls back around,
not application logic) but fine for occasional use.

Not yet built: `/predict_quali` / `/predict_race` API endpoints for the
forecast engine, frontend wiring for live forecasts, a formal backtests
module, and a persisted-predictions table. Phase 5 (chat) is deferred.
