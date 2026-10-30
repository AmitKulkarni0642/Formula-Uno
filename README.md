# Formula Uno

An F1 analytics and race-forecasting platform: FastF1-sourced data flowing
through a DuckDB/Parquet stats store into a PyTorch forecasting model and a
Monte Carlo race simulator, served by FastAPI and a Next.js frontend.

The core engineering problem: go from "replay a race that already happened"
to "forecast a race that hasn't" — without quietly leaking the answer into
the input. Most of the interesting work in this repo is the discipline
around that distinction. See [Highlights](#highlights) below, and
[`PLAN.md`](PLAN.md) / [`PROGRESS.md`](PROGRESS.md) for the full design
history and build log.

---

## Highlights

- **Leakage-safe forecasting, not replay.** A global PyTorch model (one
  network, every circuit and era) predicts lap time using only rolling
  `shift(1)`-EWM features computed *as of* the event — an event's own result
  can never leak into its own prediction. The old per-circuit XGBoost engine
  predicted qualifying using the actual race grid position, which is
  basically the answer; the new engine doesn't have that feature at all.
- **Validated honestly.** Trained on 2022-2024, evaluated on a 2025 holdout
  the model never saw: **race RMSE 3.45s / MAE 2.85s**, **qualifying RMSE
  4.57s / MAE 3.24s** — matching ten separate per-circuit specialist models
  with one general one. Validation is split by *event*, not by random lap,
  specifically to avoid mixing laps from the same race into train and test.
- **Forecasts a distribution, not a guess.** A 5,000-trial vectorized Monte
  Carlo simulation turns one pace prediction per driver into a full
  probability distribution over finishing order — stop-count, DNF rate,
  safety-car probability, pit loss, and lap noise are all measured from real
  historical data, not assumed.
- **Caught and fixed its own overconfidence.** Mexico City's small sample of
  historical races (4) all happened to have a safety car, giving a naive
  empirical probability of exactly 1.0. Fixed with Bayesian shrinkage toward
  a pooled rate (0.84, not 1.0) rather than trusting a 4-race sample as
  certainty — with a dedicated test proving the shrinkage behaves correctly
  at both small and large sample sizes.
- **Forecasts the weather, not just the race.** For a session that hasn't
  happened yet, air temperature comes from a real forecast (Open-Meteo), and
  track temperature from a circuit-specific historical offset — tested
  against a naive cross-circuit regression first, and replaced only after
  that regression was shown empirically too weak (residual std ~8.8°C).

---

## Two engines, by design

| | Reconstruction (legacy) | Forecast (active) |
|---|---|---|
| Models | One XGBoost regressor per circuit | One PyTorch MLP, global across circuits/eras |
| Input | The real session's own data (actual pit laps, actual grid) | Only data from *before* the event |
| Output | One deterministic guess | A probability distribution (Monte Carlo) |
| Endpoints | `/predict/race`, `/predict/qualifying` | `forecast_event()` — API endpoint not yet wired up |
| Status | Frozen, kept working, clearly labelled as a replay | Active development |

Both are kept in the repo on purpose, clearly separated — see
[`STRUCTURE.md`](STRUCTURE.md) for exactly which files belong to which.

---

## Stack

| Layer | Tech |
|---|---|
| Data source | [FastF1](https://docs.fastf1.dev/) 3.9 (F1TV subscription needed for full 2018-2026 telemetry) |
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

Everything backend-side goes through `run.py` for the legacy engine:

```bash
python run.py list                      # circuits/examples available to the old engine
python run.py train-all                  # train the old per-circuit XGBoost models
python run.py predict bahrain 2025       # reconstruction demo
python run.py benchmark                  # compare model families on the same data
python run.py api                        # start the FastAPI server (:8000, /docs for Swagger)
```

The forecast engine has its own CLI entry points:

```bash
python -m src.forecast.train_nn --session-type R --train-seasons 2022 2023 2024
python -m src.forecast.train_nn --session-type Q --train-seasons 2022 2023 2024
python -m src.forecast.forecast_event --season 2026 --round 19   # live forecast for a given event
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

All tests are synthetic/offline — no network calls. They check the math
(leakage-safe rolling features, Monte Carlo correctness, shrinkage
statistics, weather-combination logic) in isolation from FastF1 or any live
API, the same discipline the forecast engine itself follows.

---

## Project layout

```
src/
  ingestion/     FastF1 session loading (race + qualifying, per-lap weather)
  store/         DuckDB + Parquet processed stats store, ID/lineage mapping
  features/      Feature engineering for the old per-circuit models
  model/         XGBoost training + benchmarking (legacy reconstruction engine)
  engine/        Deterministic race-replay engine (legacy reconstruction engine)
  analytics/     Comparison, qualifying, development, telemetry analytics
  compare/       Lap/race comparison service
  forecast/      Forecast engine: pace/track rolling features, PyTorch MLP,
                 weather forecasting, live snapshots, Monte Carlo race
                 simulation, end-to-end event orchestration
  api/           FastAPI app exposing both engines
web/             Next.js frontend
tests/           pytest suite (offline/synthetic)
```

Full file-by-file breakdown: [`STRUCTURE.md`](STRUCTURE.md).

---

## Status / what's next

Forecast engine is complete for both halves of its initial scope: validated
against a true 2025 holdout, and proven end-to-end on a live, upcoming event.

Named, not hidden, simplifications: pit strategy/compound choice is a fixed
heuristic rather than a learned model; qualifying-gap spread looks narrower
than typical real-world variance; each live forecast call currently
re-sweeps historical data independently rather than sharing one load pass,
so it's slow (dominated by a flaky third-party API FastF1 falls back around,
not application logic) but fine for occasional use.

Not yet built: `/predict_quali` / `/predict_race` API endpoints for the
forecast engine, frontend wiring for live forecasts, a formal backtests
module, and a persisted-predictions table.
