# Progress

## Status

| Phase | Status |
|---|---|
| Exploration and plan | Done 26 Oct 2026. Plan in `PLAN.md`. D0 resolved 27 Oct; D1-D8 awaiting approval. |
| 1. Stats store | Not started (unblocked — D0 resolved) |
| 2. Lap comparison | Prototype shipped ad hoc (`/compare` page + `telemetry_compare.py`), not store-backed yet |
| 3. Web app | Prototype: `/compare` page only (Year/Track/Driver selectors, track map, telemetry comparison) |
| 4. Forecasts | Not started |
| 5. Chat | Not started |
| Deployment | Not started |

`src/analytics/telemetry_compare.py`, `src/api/app.py`, and `web/` have since been extended (compare page). Rest of `src/` unchanged.

## Decisions

- 26 Oct 2026, D0: use F1TV via FastF1. FastF1 upgraded 3.8.3 -> 3.9.0.
- 27 Oct 2026, D0 RESOLVED: `.env` F1_USERNAME/F1_PASSWORD confirmed working, full 2018-2026 telemetry access verified (schedule, rosters, track maps incl. year-specific layouts, grid positions, lap telemetry). `data/` now 2.9 GB, still inside OneDrive — raises the stakes on D5.
- 27 Oct 2026: shipped a telemetry comparison page ahead of the formal plan (see PLAN.md section 0) — real user-facing Phase 2/3 work, built directly against FastF1 rather than the Phase 1 store. Needs folding into Phase 1 once the store exists, not thrown away.

Other open decisions (D1-D8) are listed at the end of `PLAN.md`.

## Known limitations found during exploration

- F1's live-timing service returns HTTP 401 without an F1TV subscription (tested 26 Oct 2026). The existing cache still works; nothing new can be downloaded with FastF1 3.8.3.
- The race engine replays each race's real pit laps, compounds and in/out-lap times, and never retires a car. The qualifying predictor uses the real best quali lap and race grid. Both are reconstructions of known sessions, not forecasts.
- Models are per circuit (10 circuits), trained 2022-2024 with label-encoded drivers and teams; they cannot score unseen drivers, teams or circuits.
- Model validation uses random 5-fold CV over laps, which mixes laps from the same race into train and test.
- No tests. The project root is not a git repository (only `web/` is).
- The project sits in OneDrive; the Next.js dev server already stalls on OneDrive-synced `node_modules`.
