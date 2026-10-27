"""
Stable identifiers across seasons.

FastF1 gives us per-session names that drift — team names get rebranded
(Sauber -> Alfa Romeo -> Kick Sauber -> Audi), drivers change car numbers and
teams. Every downstream consumer (store, models, UI links, the chat agent's
tools) needs one ID that survives that drift, so it's computed once here
rather than re-derived ad hoc wherever a name is read.
"""

import re

ERAS = [(2021, "2018-21"), (2025, "2022-25")]  # upper bound inclusive; else "2026+"

# Raw per-season team name (slugified) -> one lineage id, for renamed/rebranded
# entries that are really the same constructor. Anything not listed here keeps
# its own slug as its lineage id (i.e. it hasn't been renamed in 2018-2026).
TEAM_LINEAGE: dict[str, str] = {
    # Toro Rosso -> AlphaTauri -> RB -> Racing Bulls
    "toro_rosso": "rb_lineage", "scuderia_toro_rosso": "rb_lineage",
    "alphatauri": "rb_lineage", "scuderia_alphatauri": "rb_lineage",
    "rb": "rb_lineage", "rb_f1_team": "rb_lineage",
    "visa_cash_app_rb": "rb_lineage", "visa_cash_app_rb_f1_team": "rb_lineage",
    "racing_bulls": "rb_lineage", "visa_cash_app_racing_bulls_f1_team": "rb_lineage",

    # Sauber -> Alfa Romeo -> Kick Sauber -> Audi
    "sauber": "sauber_lineage", "alfa_romeo": "sauber_lineage",
    "alfa_romeo_racing": "sauber_lineage", "alfa_romeo_racing_orlen": "sauber_lineage",
    "alfa_romeo_f1_team_orlen": "sauber_lineage", "alfa_romeo_f1_team_stake": "sauber_lineage",
    "stake_f1_team_kick_sauber": "sauber_lineage", "kick_sauber": "sauber_lineage",
    "audi": "sauber_lineage",

    # Force India -> Racing Point -> Aston Martin
    "force_india": "aston_martin_lineage", "sahara_force_india_f1_team": "aston_martin_lineage",
    "racing_point": "aston_martin_lineage", "racing_point_f1_team": "aston_martin_lineage",
    "aston_martin": "aston_martin_lineage", "aston_martin_f1_team": "aston_martin_lineage",
    "aston_martin_aramco": "aston_martin_lineage", "aston_martin_aramco_f1_team": "aston_martin_lineage",

    # Renault -> Alpine
    "renault": "alpine_lineage", "alpine": "alpine_lineage",
    "alpine_f1_team": "alpine_lineage", "bwt_alpine_f1_team": "alpine_lineage",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def event_id(season: int, round_number: int) -> str:
    return f"{season}-{round_number:02d}"


def session_id(evt_id: str, code: str) -> str:
    return f"{evt_id}-{code}"


def driver_id(full_name: str) -> str:
    """Slug of the driver's full name — stable across number/team changes."""
    return _slug(full_name)


def team_id(team_name: str) -> str:
    """Raw per-season slug: what the entry was actually called that year."""
    return _slug(team_name)


def team_lineage_id(team_name: str) -> str:
    """Groups renamed/rebranded entries (e.g. Sauber -> Audi) under one id."""
    raw = team_id(team_name)
    return TEAM_LINEAGE.get(raw, raw)


def circuit_key(location: str) -> str:
    return _slug(location)


def era_for_season(season: int) -> str:
    for upper, label in ERAS:
        if season <= upper:
            return label
    return "2026+"
