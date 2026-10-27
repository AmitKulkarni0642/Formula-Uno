# Progress

## Status

| Phase | Status |
|---|---|
| Exploration and plan | Done 26 Oct 2026. Plan in `PLAN.md`. D0, D1, D4, D5 approved+done 27 Oct; D5 (chat) deferred; D2/D3/D6/D8 proceeding on recommendation. |
| 1. Stats store | **Built 27 Oct 2026.** DuckDB + Parquet, FastF1 adapter, idempotent CLI, 14 tests passing. Bahrain 2022 Q+R ingested as proof. |
| 2. Lap comparison | Prototype shipped ad hoc (`/compare` page + `telemetry_compare.py`), still live-FastF1-backed, not store-backed yet |
| 3. Web app | Prototype: `/compare` page only (Year/Track/Driver selectors, track map, telemetry comparison) |
| 4. Forecasts | Not started (new global model approved, D1) |
| 5. Chat | Explicitly deferred by user 27 Oct — revisit after Phase 4 |
| Deployment | Not started |

`src/analytics/telemetry_compare.py`, `src/api/app.py`, and `web/` extended (compare page, pre-dating the store). New this round: `src/settings.py`, `src/store/` (ids.py, schema.sql, db.py, ingest.py, sources/fastf1_src.py), `tests/`, `requirements.txt`. Root is now a git repo (`web/`'s separate history folded in as a baseline commit).

## Decisions

- 26 Oct 2026, D0: use F1TV via FastF1. FastF1 upgraded 3.8.3 -> 3.9.0.
- 27 Oct 2026, D0 RESOLVED: `.env` F1_USERNAME/F1_PASSWORD confirmed working, full 2018-2026 telemetry access verified.
- 27 Oct 2026, D4 DONE: `git init` at root, `web/`'s one-commit history set aside (`web/.git.bak-create-next-app/`, gitignored) and folded into one root baseline commit.
- 27 Oct 2026, D5 DONE: moved `data/` (2.9 GB) from OneDrive to `C:\f1data`. One file (`fastf1_http_cache.sqlite`, 656 MB) couldn't be moved — locked by a 5-day-old orphaned `streamlit run` process still holding the FastF1 cache open. Copied instead; the stale OneDrive duplicate can be deleted once that process is stopped (user declined to let it be killed via `taskkill` at the time — low priority, just reclaims disk). `src/settings.py` (pydantic-settings) now centralizes `F1_CACHE_DIR`/`STORE_DIR`/`MODEL_DIR`; `load_session.py` and `train.py` read through it. Verified end-to-end against the new location: `predict bahrain 2025` reproduced the exact pre-move accuracy (2.9 mean pos error, 0.872s RMSE), API health/schedule endpoints green.
- 27 Oct 2026, D1 approved (new global forecasting model, Phase 4) and D5-chat deferred; D2/D3/D6/D8 proceeding per the plan's own recommendation (no separate approval needed — reversible/low-risk).
- 27 Oct 2026: shipped a telemetry comparison page ahead of the formal plan (see PLAN.md section 0) — real user-facing Phase 2/3 work, built directly against FastF1. Will be folded onto the store once Phase 2's lap-comparison engine reads from it instead.
- 27 Oct 2026, Phase 1 BUILT: `src/store/` — DuckDB relational tables (events, sessions, drivers, teams, entries, results, laps, minisectors, track_outline, corners, ingest_log) + Parquet telemetry partitions exposed as a `telemetry` view. `src/store/ids.py` gives stable IDs (event_id, session_id, driver_id slugs, team lineage mapping for Sauber->Audi/Toro Rosso->RB/Force India->Aston Martin/Renault->Alpine renames, era boundaries). `src/store/sources/fastf1_src.py` is the (only, for now) adapter — normalizes one FastF1 session into all those frames, including per-driver fastest-lap telemetry and 25-segment minisector times (linear-interpolated at ~4Hz, same honesty caveat as Phase 2's corner segmentation). `src/store/ingest.py` is the CLI (`python -m src.store.ingest --season Y [--event N] [--sessions Q,R] [--telemetry fastest|none] [--force]`), idempotent via `ingest_log` (skips sessions already `ok`; one session's failure doesn't abort the batch). Hit and fixed one real bug: DuckDB 2.0's pandas registration doesn't understand pandas' nullable `Int64` extension dtype ("data type 'Int64' not understood") — switched to plain object columns with python int/None. Verified: ingested Bahrain 2022 Q+R (1381 laps, 20 drivers, 705-point track outline, 15 corners, 1000 minisector rows, 28508 telemetry rows); re-running without `--force` correctly skips both as already-ingested. 14 tests passing (`tests/test_ingest_ids.py` — ID stability/lineage/era; `tests/test_store_idempotent.py` — replace/upsert/log never duplicate on rerun, against an in-memory DuckDB, no network). **Not yet done: the full 2018-2026 backfill** (this was one event as a correctness proof, not the backfill run) — next step.

Other open decisions (D1-D8) are listed at the end of `PLAN.md`.

## Known limitations found during exploration

- F1's live-timing service returns HTTP 401 without an F1TV subscription (tested 26 Oct 2026). The existing cache still works; nothing new can be downloaded with FastF1 3.8.3.
- The race engine replays each race's real pit laps, compounds and in/out-lap times, and never retires a car. The qualifying predictor uses the real best quali lap and race grid. Both are reconstructions of known sessions, not forecasts.
- Models are per circuit (10 circuits), trained 2022-2024 with label-encoded drivers and teams; they cannot score unseen drivers, teams or circuits.
- Model validation uses random 5-fold CV over laps, which mixes laps from the same race into train and test.
- No tests. The project root is not a git repository (only `web/` is).
- The project sits in OneDrive; the Next.js dev server already stalls on OneDrive-synced `node_modules`.
