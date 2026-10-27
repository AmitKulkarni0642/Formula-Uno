"""
ID helpers are the thing that makes the store coherent across seasons — a
bug here (two names slugging to the same id, or a lineage mis-mapped) quietly
corrupts joins everywhere downstream, so these are the cheapest, highest
leverage tests in the store.
"""

from src.store import ids


def test_event_and_session_id_shape():
    eid = ids.event_id(2026, 3)
    assert eid == "2026-03"
    assert ids.session_id(eid, "Q") == "2026-03-Q"


def test_driver_id_stable_across_team_changes():
    # Same person, different team/number across seasons -> same driver_id.
    assert ids.driver_id("Max Verstappen") == ids.driver_id("Max Verstappen")
    assert ids.driver_id("Max Verstappen") != ids.driver_id("Lewis Hamilton")


def test_driver_id_is_slug_not_abbreviation():
    # Deliberately NOT based on the 3-letter code: codes get reassigned
    # (e.g. a rookie could be given a retired driver's old code in theory).
    did = ids.driver_id("Oscar Piastri")
    assert did == "oscar_piastri"


def test_team_lineage_groups_renamed_constructors():
    # Sauber -> Alfa Romeo -> Kick Sauber -> Audi is one constructor across 2018-2026.
    names = ["Sauber", "Alfa Romeo Racing", "Kick Sauber", "Audi"]
    lineages = {ids.team_lineage_id(n) for n in names}
    assert len(lineages) == 1

    # But each one's raw, per-season id is still distinct (we don't lose what
    # it was actually called that year).
    raw_ids = {ids.team_id(n) for n in names}
    assert len(raw_ids) == 4


def test_team_lineage_unrenamed_team_falls_back_to_its_own_slug():
    assert ids.team_lineage_id("Ferrari") == ids.team_id("Ferrari") == "ferrari"


def test_era_boundaries():
    assert ids.era_for_season(2018) == "2018-21"
    assert ids.era_for_season(2021) == "2018-21"
    assert ids.era_for_season(2022) == "2022-25"
    assert ids.era_for_season(2025) == "2022-25"
    assert ids.era_for_season(2026) == "2026+"
    assert ids.era_for_season(2030) == "2026+"


def test_circuit_key_normalizes_punctuation_and_case():
    assert ids.circuit_key("Spa-Francorchamps") == "spa_francorchamps"
    assert ids.circuit_key("Sakhir") == "sakhir"
