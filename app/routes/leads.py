from fastapi import APIRouter, HTTPException
import logging
from ..models import LeadStatus, RawLead, ScoreResponse

router = APIRouter()
logger = logging.getLogger(__name__)

from ..db import get_supabase_client
from ..ai.scorer import analyze_lead, normalize_lead_intelligence

@router.post("/leads/score", response_model=ScoreResponse)
async def score_lead(lead: RawLead):
    ai_result = await analyze_lead(lead)
    scored_lead_data = normalize_lead_intelligence(lead, ai_result)
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
        )
    except Exception as exc:
        logger.exception("Lead scored but could not be persisted")
        raise HTTPException(
            status_code=503,
            detail="Lead scored but could not be saved. Verify the leads table schema is up to date.",
        ) from exc

    return ScoreResponse(**scored_lead_data, persisted=True)
