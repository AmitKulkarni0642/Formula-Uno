"""
Circuit profile data for the frontend: history text + character tags (static,
well-known facts) and lap records + last winner (computed live from our own
cached FastF1 data — never asserted from memory).
"""

import fastf1
import pandas as pd
from src.ingestion.load_session import load_race, load_qualifying

WET_COMPOUNDS = {"INTERMEDIATE", "WET"}

# Reference year for the track-map graphic. Confirmed (empirically, not assumed) that
# FastF1's live-timing mirror has full position telemetry mirrored for 2022 across all
# 10 circuits, while most 2023-2025 sessions return no data on this mirror. 2022 is also
# our regulation-era start year, so the layout is representative of the cars we model.
TRACK_MAP_YEAR = 2022


def get_track_map(event: str):
    """
    Fetch one reference lap's position telemetry and return (X, Y) arrays tracing
    the circuit outline. Returns None (not an exception) if telemetry genuinely
    isn't available for this circuit — callers should handle that gracefully.
    """
    try:
        session = fastf1.get_session(TRACK_MAP_YEAR, event, "R")
        session.load(telemetry=True, weather=False, messages=False)
        lap = session.laps.pick_fastest()
        tel = lap.get_telemetry()
        if tel is None or tel.empty:
            return None
        return tel["X"].to_numpy(), tel["Y"].to_numpy()
    except Exception:
        return None

# Well-known, low-risk factual notes — character tags and brief history, not
# precise numeric claims (lengths/corner counts) we can't verify from our data.
CIRCUIT_INFO = {
    "bahrain": {
        "nickname": "Bahrain International Circuit, Sakhir",
        "tags": ["Permanent circuit", "Night race", "Desert venue"],
        "history": (
            "The first circuit in the Middle East to host a Formula 1 race, in 2004. "
            "It has run as a floodlit night race since 2014 and is a regular "
            "pre-season testing venue, making it one of the best-understood "
            "circuits on the calendar."
        ),
    },
    "spa": {
        "nickname": "Circuit de Spa-Francorchamps",
        "tags": ["Permanent circuit", "High-speed", "Historic"],
        "history": (
            "One of the oldest circuits still on the calendar, famous for the "
            "Eau Rouge–Raidillon corner complex and the long Kemmel straight. "
            "Its elevation change and famously unpredictable Ardennes weather "
            "make it a demanding test of car and driver alike."
        ),
    },
    "austria": {
        "nickname": "Red Bull Ring",
        "tags": ["Permanent circuit", "Short lap", "Mountain scenery"],
        "history": (
            "Set in the Styrian mountains, this is one of the shortest circuits "
            "on the calendar — a handful of corners linked by long straights. It "
            "has raced under several earlier names (Österreichring, A1-Ring) "
            "before its current identity."
        ),
    },
    "australia": {
        "nickname": "Albert Park, Melbourne",
        "tags": ["Park circuit", "Traditional season opener"],
        "history": (
            "A temporary circuit laid out through a public park beside Albert "
            "Lake, long one of the sport's traditional season-opening venues. "
            "The layout was reprofiled for 2022, removing several chicanes to "
            "encourage faster, more flowing racing."
        ),
    },
    "monza": {
        "nickname": "Autodromo Nazionale Monza",
        "tags": ["Permanent circuit", "Low-downforce", "Historic", "High-speed"],
        "history": (
            "The 'Temple of Speed' — long straights and heavy braking zones "
            "where cars run their lowest-drag setup of the season. It has "
            "hosted the Italian Grand Prix almost every year since the first "
            "F1 World Championship in 1950."
        ),
    },
    "abudhabi": {
        "nickname": "Yas Marina Circuit",
        "tags": ["Permanent circuit", "Night race", "Recent season finale"],
        "history": (
            "Host of the Abu Dhabi Grand Prix since 2009, with a twilight-into-"
            "night race around a marina setting. It has frequently closed out "
            "the championship, and has been reprofiled in recent years to "
            "sharpen the on-track action."
        ),
    },
    "mexico": {
        "nickname": "Autódromo Hermanos Rodríguez",
        "tags": ["Permanent circuit", "High altitude", "Stadium section"],
        "history": (
            "Sitting at roughly 2,200 metres above sea level, this is one of "
            "the highest-altitude venues in the sport — thin air that "
            "meaningfully changes how the cars' aerodynamics and engines "
            "behave. The final sector loops through a stadium section packed "
            "with fans."
        ),
    },
    "monaco": {
        "nickname": "Circuit de Monaco",
        "tags": ["Street circuit", "Narrowest circuit", "Prestige event"],
        "history": (
            "Run on the streets of Monte Carlo since 1929. Monaco is the "
            "slowest and narrowest circuit on the calendar, where overtaking "
            "is notoriously difficult and grid position often decides the race."
        ),
    },
    "canada": {
        "nickname": "Circuit Gilles Villeneuve",
        "tags": ["Park circuit", "Heavy braking", "'Wall of Champions'"],
        "history": (
            "Built on Notre Dame Island in Montreal and named after Canadian "
            "driver Gilles Villeneuve. Its final chicane wall earned the "
            "nickname the 'Wall of Champions' after catching out several "
            "title winners over the years."
        ),
    },
    "silverstone": {
        "nickname": "Silverstone Circuit",
        "tags": ["Permanent circuit", "High-speed corners", "First-ever F1 race"],
        "history": (
            "A former WWII airfield that hosted the first-ever round of the "
            "Formula 1 World Championship in 1950. Its sweeping high-speed "
            "sequence — Maggotts, Becketts, Copse — is regarded as one of the "
            "most demanding in the sport."
        ),
    },
}


def get_profile(circuit_key: str) -> dict:
    return CIRCUIT_INFO.get(circuit_key, {
        "nickname": circuit_key.title(), "tags": [], "history": "",
    })


def get_last_winner(circuit_key: str, event: str, year: int = 2025) -> dict | None:
    """The actual race winner for the given (most recent, by default) year — from real results."""
    try:
        results = load_race(year, event)["results"]
    except Exception:
        return None
    winners = results[pd.to_numeric(results["Position"], errors="coerce") == 1]
    if winners.empty:
        return None
    row = winners.iloc[0]
    return {"driver": row["Abbreviation"], "team": row["TeamName"], "year": year}


# Standard FIA/F1 tyre compound colors — widely recognized convention.
COMPOUND_COLORS = {
    "SOFT": "#FF3333", "MEDIUM": "#FFF200", "HARD": "#F0F0F0",
    "INTERMEDIATE": "#43B02A", "WET": "#0067AD",
}


def get_strategy(event: str, year: int) -> pd.DataFrame:
    """
    Real tyre strategy for every driver — the actual stints run (compound, start
    lap, end lap), taken directly from historical data. This is an INPUT the race
    engine replays (real pit laps, real compounds), not a model prediction, so
    there's no predicted-vs-actual version of this chart.

    Returns one row per (driver, stint): driver, team, finish_position, compound,
    start_lap, end_lap, stint_length.
    """
    race = load_race(year, event)
    laps, results = race["laps"], race["results"]

    pos_map = dict(zip(results["Abbreviation"],
                        pd.to_numeric(results["Position"], errors="coerce")))

    rows = []
    for (driver, stint), g in laps.dropna(subset=["Stint", "Compound"]).groupby(["Driver", "Stint"]):
        rows.append({
            "driver": driver,
            "team": g["Team"].iloc[0],
            "finish_position": pos_map.get(driver, 99),
            "compound": g["Compound"].iloc[0],
            "start_lap": int(g["LapNumber"].min()),
            "end_lap": int(g["LapNumber"].max()),
        })
    df = pd.DataFrame(rows)
    df["stint_length"] = df["end_lap"] - df["start_lap"] + 1
    return df.sort_values(["finish_position", "start_lap"])


def get_lap_records(circuit_key: str, event: str, years: list[int]) -> dict:
    """
    Fastest clean race lap and fastest clean qualifying lap across our own cached
    data (dry/accurate laps only) — computed directly, never asserted from memory.
    """
    out = {"race": None, "quali": None}
    for session_type, loader in (("race", load_race), ("quali", load_qualifying)):
        best = None
        for yr in years:
            try:
                laps = loader(yr, event)["laps"].copy()
            except Exception:
                continue
            laps["s"] = laps["LapTime"].dt.total_seconds()
            clean = laps[
                laps["IsAccurate"] & laps["s"].notna()
                & ~laps["Compound"].isin(WET_COMPOUNDS)
            ]
            if clean.empty:
                continue
            row = clean.loc[clean["s"].idxmin()]
            if best is None or row["s"] < best["time_s"]:
                best = {"driver": row["Driver"], "team": row["Team"],
                        "time_s": float(row["s"]), "year": yr}
        out[session_type] = best
    return out
