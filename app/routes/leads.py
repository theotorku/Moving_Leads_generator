from fastapi import APIRouter, HTTPException
import logging
from ..models import LeadStatus, RawLead, ScoreResponse

router = APIRouter()
logger = logging.getLogger(__name__)

from ..db import get_supabase_client
from ..ai.scorer import analyze_lead, normalize_lead_intelligence
from ..ai.calibration import calibrate

@router.post("/leads/score", response_model=ScoreResponse)
async def score_lead(lead: RawLead):
    ai_result = await analyze_lead(lead)
    scored_lead_data = normalize_lead_intelligence(lead, ai_result)

    # Outcomes -> scoring: blend the AI booking probability toward this segment's
    # real conversion history (and nudge fraud risk on high-dispute segments).
    # Best-effort — never block scoring if the lookup fails.
    calibration = None
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
        calibration = adjusted["calibration"]
    except RuntimeError:
        pass  # Supabase not configured; nothing to calibrate against
    except Exception:
        logger.exception("Calibration skipped")

    stored_lead_data = {**scored_lead_data, "status": LeadStatus.available.value}

    # Persist to Supabase. We no longer silently swallow failures: a genuine
    # insert error (e.g. schema drift) fails loudly so it can't masquerade as
    # success, while an unconfigured database degrades to a clear warning.
    try:
        get_supabase_client().table("leads").insert(stored_lead_data).execute()
    except RuntimeError:
        logger.warning("Lead scored but not persisted because Supabase is not configured.")
        return ScoreResponse(
            **scored_lead_data,
            persisted=False,
            persistence_warning="Supabase is not configured; the lead was scored but not saved.",
            calibration=calibration,
        )
    except Exception as exc:
        logger.exception("Lead scored but could not be persisted")
        raise HTTPException(
            status_code=503,
            detail="Lead scored but could not be saved. Verify the leads table schema is up to date.",
        ) from exc

    return ScoreResponse(**scored_lead_data, persisted=True, calibration=calibration)
