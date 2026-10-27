"""
Plain-English, templated summaries of where time was gained/lost, ranked by
magnitude. No LLM: every number traces directly to a segment's measured
metric — the same rule Phase 5's chat agent follows for its tool results.
"""

MIN_REPORTABLE_DELTA_S = 0.01


def rank_insights(segments: list[dict], driver_a: str, driver_b: str, max_insights: int = 5) -> list[str]:
    reportable = [s for s in segments if abs(s["time_delta_s"]) >= MIN_REPORTABLE_DELTA_S]
    ranked = sorted(reportable, key=lambda s: abs(s["time_delta_s"]), reverse=True)

    out = []
    for seg in ranked[:max_insights]:
        amount = abs(seg["time_delta_s"])
        b_ahead = seg["time_delta_s"] < 0  # delta_ms = t_B - t_A, so negative means B is quicker here
        gainer, loser = (driver_b, driver_a) if b_ahead else (driver_a, driver_b)
        where = f"Corner {seg['corner']}" if seg.get("corner") is not None else "this section"

        if seg["category"] == "braking" and seg["braking_point_diff_m"]:
            gainer_braked_later = (seg["braking_point_diff_m"] > 0) == b_ahead
            detail = f"braked {abs(seg['braking_point_diff_m']):.0f}m " + ("later" if gainer_braked_later else "earlier")
            out.append(f"{where}: {gainer} gained {amount:.3f}s — {detail} than {loser}.")
        elif seg["category"] == "apex":
            out.append(
                f"{where}: {gainer} gained {amount:.3f}s — carried "
                f"{abs(seg['min_speed_diff_kmh']):.0f} km/h more through the apex than {loser}."
            )
        elif seg["category"] == "traction":
            out.append(
                f"{where}: {gainer} gained {amount:.3f}s on exit — "
                f"{abs(seg['exit_speed_diff_kmh']):.0f} km/h faster off the corner than {loser}."
            )
        else:
            out.append(
                f"{where}: {gainer} gained {amount:.3f}s — "
                f"{abs(seg['top_speed_diff_kmh']):.0f} km/h faster on the straight than {loser}."
            )
    return out
