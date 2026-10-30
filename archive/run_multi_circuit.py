from src.pipeline import run_multi_circuit

run_multi_circuit(
    circuits=[
        {"event": "Bahrain Grand Prix",     "track_label": "Bahrain"},
        {"event": "Belgian Grand Prix",     "track_label": "Spa"},
        {"event": "Austrian Grand Prix",    "track_label": "Austria"},
        {"event": "Australian Grand Prix",  "track_label": "Australia"},
        {"event": "Italian Grand Prix",     "track_label": "Monza"},
        {"event": "Abu Dhabi Grand Prix",   "track_label": "AbuDhabi"},
        {"event": "Mexico City Grand Prix", "track_label": "Mexico"},
        {"event": "Monaco Grand Prix",      "track_label": "Monaco"},
        {"event": "Canadian Grand Prix",    "track_label": "Canada"},
        {"event": "British Grand Prix",     "track_label": "Silverstone"},
    ],
    train_years=[2022, 2023, 2024],
    test_year=2025,
)
