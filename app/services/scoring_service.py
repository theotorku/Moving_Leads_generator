"""Shared lead scoring + persistence pipeline.

Both the public form (`POST /leads/score`), the partner intake endpoint
(`POST /leads/intake`), and the admin CSV import run a lead through the same
steps: AI intelligence -> outcome calibration -> attach source/consent
provenance -> persist to the RLS-locked `leads` table. Keeping that in one place
means every channel scores and stores leads identically.
"""
from datetime import datetime, timezone
import logging

from fastapi import HTTPException

from ..ai.calibration import calibrate
from ..ai.scorer import analyze_lead, normalize_lead_intelligence
from ..db import get_supabase_client
from ..models import LeadStatus, RawLead

logger = logging.getLogger(__name__)


def _apply_calibration(scored_lead_data: dict, lead: RawLead):
    """Blend the AI booking probability toward this segment's real conversion
    history (best-effort — never block scoring if the lookup fails)."""
    try:
        stats = get_supabase_client().rpc(
            "lead_segment_stats",
            {"p_route_type": scored_lead_data.get("route_type"), "p_urgency": lead.urgency},
        ).execute().data or {}
        adjusted = calibrate(
            scored_lead_data.get("booking_probability", 0),
            scored_lead_data.get("fraud_risk"),
            stats,
        )
        scored_lead_data["booking_probability"] = adjusted["booking_probability"]
        scored_lead_data["fraud_risk"] = adjusted["fraud_risk"]
        return adjusted["calibration"]
    except RuntimeError:
        return None  # Supabase not configured; nothing to calibrate against
    except Exception:
        logger.exception("Calibration skipped")
        return None


async def score_and_store_lead(
    lead: RawLead,
    *,
    source_fields: dict,
    source_ip: str | None = None,
    verified: bool = False,
    status: str = LeadStatus.available.value,
) -> dict:
    """Score a lead, calibrate it, attach provenance, and persist it.

    `source_fields` holds the resolved attribution (source, source_channel,
    source_medium/campaign/referrer/partner, source_url, landing_page). The
    caller decides where those come from — derived from a browser request, an
    intake API key, or a CSV row.

    Returns a dict: the scored lead data plus `persisted`, `persistence_warning`,
    and `calibration`. Raises on a genuine insert failure (schema drift) so it
    can't masquerade as success.
    """
    ai_result = await analyze_lead(lead)
    scored_lead_data = normalize_lead_intelligence(lead, ai_result)
    calibration = _apply_calibration(scored_lead_data, lead)

    scored_lead_data.update(source_fields)
    consented = bool(scored_lead_data.get("consent_tcpa"))
    stored_lead_data = {
        **scored_lead_data,
        "status": status,
        "source_ip": source_ip,
        "consent_at": datetime.now(timezone.utc).isoformat() if consented else None,
        "verified": verified,
    }

    try:
        get_supabase_client().table("leads").insert(stored_lead_data).execute()
    except RuntimeError:
        logger.warning("Lead scored but not persisted because Supabase is not configured.")
        return {
            "scored_lead_data": scored_lead_data,
            "persisted": False,
            "persistence_warning": "Supabase is not configured; the lead was scored but not saved.",
            "calibration": calibration,
        }
    except Exception as exc:
        # A genuine insert error (e.g. schema drift) must fail loudly, not
        # masquerade as success.
        logger.exception("Lead scored but could not be persisted")
        raise HTTPException(
            status_code=503,
            detail="Lead scored but could not be saved. Verify the leads table schema is up to date.",
        ) from exc

    return {
        "scored_lead_data": scored_lead_data,
        "persisted": True,
        "persistence_warning": None,
        "calibration": calibration,
    }
