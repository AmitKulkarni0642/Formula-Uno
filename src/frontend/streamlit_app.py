"""
Formula Uno — Streamlit frontend (Stage 2).

Calls predict_race() / predict_qualifying_for() directly — the same compute-layer
functions the FastAPI endpoints call. No HTTP round trip: this app imports the
service module in-process, exactly the reuse the compute/transport split in
predict_service.py was designed to make trivial.

Run with:  python run.py frontend
       or: python -m streamlit run src/frontend/streamlit_app.py
"""

import sys
from pathlib import Path

import altair as alt
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# Make the project importable regardless of Streamlit's own cwd handling.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.predict_service import (
    available_circuits, predict_race, predict_qualifying_for, get_lap_trace,
    get_pit_recommendation, CIRCUITS, SERVE_YEARS,
)
from src.frontend.circuit_profile import (
    get_profile, get_last_winner, get_lap_records, get_track_map,
    get_strategy, COMPOUND_COLORS,
)

st.set_page_config(page_title="Formula Uno", page_icon="🏎️", layout="wide")


@st.cache_data(show_spinner=False)
def _race(circuit: str, year: int) -> dict:
    return predict_race(circuit, year)


@st.cache_data(show_spinner=False)
def _qual(circuit: str, year: int) -> dict:
    return predict_qualifying_for(circuit, year)


@st.cache_data(show_spinner=False)
def _trace(circuit: str, year: int, driver: str) -> dict:
    return get_lap_trace(circuit, year, driver)


@st.cache_data(show_spinner=False)
def _strategy(circuit: str, year: int) -> pd.DataFrame:
    return get_strategy(CIRCUITS[circuit]["event"], year)


@st.cache_data(show_spinner=False)
def _pit_rec(circuit: str, year: int, driver: str) -> dict | None:
    return get_pit_recommendation(circuit, year, driver)


@st.cache_data(show_spinner=False)
def _track_map(circuit: str) -> tuple | None:
    event = CIRCUITS[circuit]["event"]
    return get_track_map(event)


@st.cache_data(show_spinner=False)
def _profile_facts(circuit: str) -> dict:
    """Last winner + lap records — computed once per circuit, independent of the
    year/session controls, so switching those doesn't re-trigger this."""
    event = CIRCUITS[circuit]["event"]
    return {
        "winner": get_last_winner(circuit, event, max(SERVE_YEARS)),
        "records": get_lap_records(circuit, event, sorted(SERVE_YEARS)),
    }


# ---------------------------------------------------------------------------
# Sidebar — controls
# ---------------------------------------------------------------------------

circuits = available_circuits()
labels = {c["label"]: c["key"] for c in circuits}

st.sidebar.title("🏎️ Formula Uno")
st.sidebar.caption("A learned pace model reconstructing F1 races and grids.")

circuit_label = st.sidebar.selectbox("Circuit", sorted(labels.keys()))
circuit_key = labels[circuit_label]

year = st.sidebar.selectbox("Season", sorted(SERVE_YEARS, reverse=True))

session = st.sidebar.radio("Session", ["Race", "Qualifying"], horizontal=True)

with st.sidebar.expander("How this works"):
    st.markdown(
        "Each circuit has its own XGBoost model, trained only on **that circuit's** "
        "2022–2024 laps (fuel load, tyre age, compound, track/air temperature, grid "
        "position, driver/team identity). **2025 is never seen during training** — "
        "it's the honest out-of-sample test. The race engine replays a Grand Prix "
        "lap by lap, accumulating predicted lap times; finishing order *emerges* from "
        "that, it's never set directly."
    )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.title(f"{circuit_label} — {year}")

# ---------------------------------------------------------------------------
# Circuit profile — track map, history, character, last winner, lap records
# ---------------------------------------------------------------------------
map_col, info_col = st.columns([1, 2])

with map_col:
    with st.spinner("Loading track map..."):
        xy = _track_map(circuit_key)
    if xy is not None:
        x, y = xy
        fig, ax = plt.subplots(figsize=(3.6, 3.6))
        fig.patch.set_alpha(0)
        ax.set_facecolor("none")
        ax.plot(x, y, color="#E10600", linewidth=2.5, solid_capstyle="round")
        ax.plot(x[0], y[0], "o", color="#E10600", markersize=7)
        ax.set_aspect("equal")
        ax.axis("off")
        st.pyplot(fig, use_container_width=True)
        st.caption(f"Reference lap: {get_profile(circuit_key)['nickname']}, {2022} race")
    else:
        st.info("Track map unavailable for this circuit (no mirrored telemetry).")

with info_col:
    profile = get_profile(circuit_key)
    st.subheader(profile["nickname"])
    if profile["tags"]:
        st.write(" ".join(f":blue-badge[{t}]" for t in profile["tags"]))
    if profile["history"]:
        st.caption(profile["history"])

    with st.spinner("Loading circuit facts..."):
        facts = _profile_facts(circuit_key)

    fc1, fc2, fc3 = st.columns(3)
    winner = facts["winner"]
    with fc1:
        st.metric(f"Last winner ({max(SERVE_YEARS)})",
                  f"{winner['driver']} ({winner['team']})" if winner else "—")
    race_rec = facts["records"]["race"]
    with fc2:
        st.metric("Fastest race lap (2022–25)",
                  f"{race_rec['time_s']:.3f}s" if race_rec else "—",
                  help=f"{race_rec['driver']} ({race_rec['team']}), {race_rec['year']}" if race_rec else None)
    quali_rec = facts["records"]["quali"]
    with fc3:
        st.metric("Fastest qualifying lap (2022–25)",
                  f"{quali_rec['time_s']:.3f}s" if quali_rec else "—",
                  help=f"{quali_rec['driver']} ({quali_rec['team']}), {quali_rec['year']}" if quali_rec else None)

st.divider()

try:
    with st.spinner(f"Simulating {circuit_label} {year}..."):
        data = _race(circuit_key, year) if session == "Race" else _qual(circuit_key, year)
except Exception as e:
    st.error(f"Couldn't generate a prediction: {e}")
    st.stop()

badge_col, meta_col = st.columns([1, 3])
with badge_col:
    if session == "Race":
        st.badge("In-sample" if data["in_sample"] else "Out-of-sample",
                  color="blue" if data["in_sample"] else "orange")
with meta_col:
    st.caption(f"Model: `{data['model']}`  ·  Approach: **{data['approach']}**")

st.divider()

# ---- Metrics row ----
m = data["metrics"]
if session == "Race":
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mean position error", f"{m['mean_position_error']:.2f} places")
    c2.metric("Fleet lap-time RMSE", f"{m['fleet_lap_rmse_s']:.3f}s" if m["fleet_lap_rmse_s"] is not None else "—")
    c3.metric("Within 2 positions", f"{m['within_2_positions']}/{m['drivers_compared']}")
    c4.metric("Exact positions", f"{m['exact_positions']}/{m['drivers_compared']}")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mean grid error", f"{m['mean_grid_error']:.2f} places")
    c2.metric("Lap-time RMSE", f"{m['lap_time_rmse_s']:.3f}s")
    c3.metric("Within 2 positions", f"{m['within_2_positions']}/{m['drivers']}")
    c4.metric("Exact positions", f"{m['exact_positions']}/{m['drivers']}")

st.divider()

# ---- Results table + chart ----
results = pd.DataFrame(data["results"])

table_col, chart_col = st.columns([3, 2])

if session == "Race":
    with table_col:
        st.subheader("Predicted vs. actual finishing order")
        show = results.rename(columns={
            "sim_position": "Predicted", "driver": "Driver", "team": "Team",
            "actual_position": "Actual", "position_error": "Error", "lap_rmse_s": "Lap RMSE (s)",
        })[["Predicted", "Driver", "Team", "Actual", "Error", "Lap RMSE (s)"]]
        st.dataframe(
            show.style.background_gradient(subset=["Error"], cmap="Reds"),
            hide_index=True, use_container_width=True, height=740,
        )
    with chart_col:
        st.subheader("Position error by driver")
        chart_df = results.sort_values("position_error", ascending=False).set_index("driver")
        st.bar_chart(chart_df["position_error"], horizontal=True)
else:
    with table_col:
        st.subheader("Predicted vs. actual grid")
        show = results.rename(columns={
            "pred_grid": "Predicted", "driver": "Driver", "team": "Team",
            "predicted_time_s": "Predicted (s)", "actual_time_s": "Actual (s)",
            "actual_grid": "Actual", "grid_error": "Error",
        })[["Predicted", "Driver", "Team", "Predicted (s)", "Actual (s)", "Actual", "Error"]]
        st.dataframe(
            show.style.background_gradient(subset=["Error"], cmap="Reds"),
            hide_index=True, use_container_width=True, height=740,
        )
    with chart_col:
        st.subheader("Grid error by driver")
        chart_df = results.sort_values("grid_error", ascending=False).set_index("driver")
        st.bar_chart(chart_df["grid_error"], horizontal=True)

if session == "Race":
    st.divider()
    st.subheader("Tyre strategy")
    st.caption(
        "The real strategy every driver ran — actual compounds and pit laps. The "
        "simulation replays these exact stops using real historical times, so there's "
        "no predicted version of this chart; it's shown for context."
    )
    strat = _strategy(circuit_key, year)
    if not strat.empty:
        driver_order = strat.sort_values("finish_position")["driver"].unique().tolist()
        strat_chart = (
            alt.Chart(strat)
            .mark_bar(height=14)
            .encode(
                x=alt.X("start_lap:Q", title="Lap"),
                x2="end_lap:Q",
                y=alt.Y("driver:N", sort=driver_order, title=None),
                color=alt.Color("compound:N", title="Compound",
                                scale=alt.Scale(domain=list(COMPOUND_COLORS.keys()),
                                                range=list(COMPOUND_COLORS.values()))),
                tooltip=["driver", "compound", "start_lap", "end_lap", "stint_length"],
            )
            .properties(height=26 * len(driver_order))
        )
        st.altair_chart(strat_chart, use_container_width=True)
    else:
        st.info("No strategy data available for this session.")

    st.divider()
    st.subheader("Lap-by-lap: predicted vs. actual")
    driver_options = sorted(results["driver"].tolist())
    default_driver = results.loc[results["sim_position"].idxmin(), "driver"]
    chosen = st.selectbox(
        "Driver", driver_options,
        index=driver_options.index(default_driver) if default_driver in driver_options else 0,
    )
    with st.spinner(f"Building {chosen}'s lap trace..."):
        trace = _trace(circuit_key, year, chosen)

    tab_time, tab_pos, tab_gap, tab_pit = st.tabs(
        ["Lap time", "Position", "Gap to leader", "Pit window"])

    with tab_time:
        trace_df = pd.DataFrame({
            "Lap": trace["laps"], "Predicted": trace["predicted_s"], "Actual": trace["actual_s"],
        }).set_index("Lap")
        st.line_chart(trace_df, color=["#FF4B4B", "#1F77B4"])
        st.caption(
            "In-lap/out-lap pit stops use real historical times in both series (the model was "
            "never trained on them), so they typically line up exactly."
        )

    with tab_pos:
        pos_df = pd.DataFrame({
            "Lap": trace["laps"], "Predicted": trace["predicted_position"], "Actual": trace["actual_position"],
        }).melt("Lap", var_name="Series", value_name="Position").dropna()
        pos_chart = (
            alt.Chart(pos_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("Lap:Q", axis=alt.Axis(tickMinStep=1, format="d")),
                # Positions are always whole numbers (P1, P2, ...) — force integer
                # ticks, and reverse the scale so P1 sits at the top, matching how
                # a race position chart is normally read.
                y=alt.Y("Position:Q", axis=alt.Axis(tickMinStep=1, format="d"),
                        scale=alt.Scale(reverse=True)),
                color=alt.Color("Series:N", scale=alt.Scale(
                    domain=["Predicted", "Actual"], range=["#FF4B4B", "#1F77B4"])),
            )
        )
        st.altair_chart(pos_chart, use_container_width=True)
        st.caption("P1 at the top. Shows whether a position error builds gradually over "
                   "the race or comes from one bad lap.")

    with tab_gap:
        gap_df = pd.DataFrame({
            "Lap": trace["laps"], "Predicted": trace["predicted_gap_s"], "Actual": trace["actual_gap_s"],
        }).set_index("Lap")
        st.line_chart(gap_df, color=["#FF4B4B", "#1F77B4"])
        st.caption(
            "Seconds behind the race leader at each lap. The actual series uses FastF1's "
            "recorded session clock time, so it stays correct through Safety Car / VSC "
            "periods; the model has no incident awareness, so its predicted gap won't react "
            "to one."
        )

    with tab_pit:
        st.caption(
            "A tyre-degradation-only read, not a strategy predictor: using the model's own "
            "learned lap-time-vs-tyre-age curve for the driver's opening stint, this finds "
            "the tyre age where staying out has cost more time than a pit stop would — "
            "nothing else. Real strategy (undercuts, Safety Cars, traffic) is outside what "
            "any of our features can see."
        )
        with st.spinner("Computing degradation curve..."):
            rec = _pit_rec(circuit_key, year, chosen)

        if rec is None:
            st.info(f"No stint data available for {chosen} this race.")
        else:
            curve = rec["degradation_curve"]
            curve_df = pd.DataFrame({
                "Tyre age": curve["tyre_age"], "Predicted lap time (s)": curve["predicted_lap_s"],
            }).set_index("Tyre age")
            st.line_chart(curve_df, color=["#FF4B4B"])

            actual_age = rec["actual_pit_lap"] - rec["start_lap"] + 1
            total_rise = curve["predicted_lap_s"][-1] - curve["predicted_lap_s"][0]
            c1, c2, c3 = st.columns(3)
            c1.metric("Actual pit lap", f"L{rec['actual_pit_lap']}", help=f"Tyre age {actual_age}")
            c2.metric("Model's recommended lap",
                      f"L{rec['recommended_pit_lap']}" if rec["recommended_pit_lap"] else "No clear signal")
            c3.metric("Est. pit-stop time loss", f"{rec['pit_loss_s']}s",
                      help="Median in-lap + out-lap time loss vs. clean pace, from our own historical data.")

            if rec["recommended_pit_lap"] is None:
                st.warning(
                    f"The model predicts only **{total_rise:.2f}s** of total degradation across "
                    f"{curve['tyre_age'][-1]} laps on {rec['compound'].title()} tyres — too flat to "
                    "generate a confident recommendation. This is an honest limitation: our lap-time "
                    "model was never given a strong enough degradation signal to answer this question "
                    "reliably (tyre-related features are a small share of what drives its predictions). "
                    "The real pit stop was almost certainly decided by strategy, not pure tyre wear."
                )
            else:
                early_late = "earlier (undercut-style)" if rec["actual_pit_lap"] < rec["recommended_pit_lap"] else \
                             "later (overcut-style)" if rec["actual_pit_lap"] > rec["recommended_pit_lap"] else "right on"
                st.caption(f"The real stop came in {early_late} than the tyre-physics-only recommendation.")

st.divider()
st.caption(
    "Formula Uno — physics-informed lap-time models, cross-year validated. "
    "Built on FastF1 timing data, 2022–2025."
)
