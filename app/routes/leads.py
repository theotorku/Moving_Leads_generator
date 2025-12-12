from fastapi import APIRouter, HTTPException
from ..models import RawLead, ScoredLead

router = APIRouter()

from ..db import supabase
from ..ai.scorer import analyze_lead

@router.post("/leads/score", response_model=ScoredLead)
async def score_lead(lead: RawLead):
    # Use AI to score the lead
    ai_result = await analyze_lead(lead)
    
    score = ai_result.get("score", 0)
    reasoning = ai_result.get("reasoning", "No reasoning provided.")
    
    scored_lead_data = lead.dict()
    # Convert date objects to ISO strings for JSON serialization
    if scored_lead_data.get("move_date"):
        scored_lead_data["move_date"] = scored_lead_data["move_date"].isoformat()
        
    scored_lead_data.update({"score": score, "reasoning": reasoning})
    
    # Persist to Supabase
    try:
        supabase.table("leads").insert(scored_lead_data).execute()
    except Exception as e:
        # In production, we might log this error but still return the score,
        # or raise a 500 depending on requirements. For now, we print it.
        print(f"Error saving to DB: {e}")
        import traceback
        traceback.print_exc()

    return ScoredLead(**scored_lead_data)