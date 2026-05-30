from fastapi import APIRouter
import logging
from ..models import LeadStatus, RawLead, ScoredLead

router = APIRouter()
logger = logging.getLogger(__name__)

from ..db import get_supabase_client
from ..ai.scorer import analyze_lead, normalize_lead_intelligence

@router.post("/leads/score", response_model=ScoredLead)
async def score_lead(lead: RawLead):
    ai_result = await analyze_lead(lead)
    scored_lead_data = normalize_lead_intelligence(lead, ai_result)
    stored_lead_data = {**scored_lead_data, "status": LeadStatus.available.value}
    
    # Persist to Supabase
    try:
        get_supabase_client().table("leads").insert(stored_lead_data).execute()
    except RuntimeError:
        logger.warning("Lead scored but not persisted because Supabase is not configured.")
    except Exception:
        logger.exception("Lead scored but could not be persisted")

    return ScoredLead(**scored_lead_data)
