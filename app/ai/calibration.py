"""Calibrate a new lead's booking probability against real outcomes.

The AI scorer estimates booking probability from a lead's attributes in
isolation. Once leads in a segment (route_type + urgency) have actually been
sold and worked, we know the *real* book rate — so we blend the AI estimate
toward that empirical rate using shrinkage (so small samples barely move the
number, large samples dominate). High dispute rates also nudge fraud risk up.

Pure and deterministic — the DB lookup happens in the caller; this just does the
math, which keeps it explainable and unit-testable.
"""
from __future__ import annotations

# Shrinkage weight: with fewer than this many sales the AI estimate dominates.
SMOOTHING_K = 5
# Below this sample size we don't calibrate at all.
MIN_SAMPLE = 3
# Segment dispute rate at/above this bumps fraud risk one level.
DISPUTE_BUMP_THRESHOLD = 0.20

_RISK_ORDER = ["low", "medium", "high"]


def _bump_risk(risk: str | None) -> str:
    try:
        idx = _RISK_ORDER.index((risk or "medium").lower())
    except ValueError:
        return "high"
    return _RISK_ORDER[min(idx + 1, len(_RISK_ORDER) - 1)]


def calibrate(ai_booking_probability: int, fraud_risk: str | None, stats: dict | None) -> dict:
    """Return calibrated booking_probability / fraud_risk plus an explanation.

    stats: {"n", "booked", "disputed"} for the lead's segment (from the RPC).
    """
    ai_bp = max(0, min(100, int(ai_booking_probability or 0)))
    stats = stats or {}
    n = int(stats.get("n") or 0)
    booked = int(stats.get("booked") or 0)
    disputed = int(stats.get("disputed") or 0)

    if n < MIN_SAMPLE:
        return {
            "booking_probability": ai_bp,
            "fraud_risk": fraud_risk,
            "calibration": {
                "applied": False,
                "sample_size": n,
                "note": f"Not enough sales history in this segment ({n}); using the AI estimate.",
            },
        }

    empirical_bp = round(booked / n * 100)
    dispute_rate = disputed / n
    calibrated = round((n * empirical_bp + SMOOTHING_K * ai_bp) / (n + SMOOTHING_K))
    calibrated = max(0, min(100, calibrated))

    new_risk = _bump_risk(fraud_risk) if dispute_rate >= DISPUTE_BUMP_THRESHOLD else fraud_risk

    note = (
        f"Calibrated from {n} past sales in this segment "
        f"({empirical_bp}% booked, {round(dispute_rate * 100)}% disputed)."
    )
    if new_risk != fraud_risk:
        note += f" Fraud risk raised to {new_risk} (high dispute rate)."

    return {
        "booking_probability": calibrated,
        "fraud_risk": new_risk,
        "calibration": {
            "applied": True,
            "sample_size": n,
            "historical_book_rate": empirical_bp,
            "historical_dispute_rate": round(dispute_rate * 100),
            "adjusted_from": ai_bp,
            "adjusted_to": calibrated,
            "note": note,
        },
    }
