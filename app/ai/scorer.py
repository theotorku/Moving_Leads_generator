import json
import logging
from functools import lru_cache

from openai import AsyncOpenAI
from pydantic import ValidationError

from ..config import get_settings
from ..models import HomeSize, LeadUrgency, MoveComplexity, RawLead, RiskLevel, RouteType, ScoredLead

logger = logging.getLogger(__name__)


@lru_cache
def get_openai_client() -> AsyncOpenAI | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


def _infer_route_type(lead: RawLead) -> str:
    if lead.origin_zip[:1] != lead.destination_zip[:1]:
        return RouteType.interstate.value
    if lead.origin_zip[:3] != lead.destination_zip[:3]:
        return RouteType.intrastate.value
    return RouteType.local.value


def _infer_complexity(lead: RawLead) -> str:
    high_complexity_sizes = {HomeSize.three_bedroom.value, HomeSize.four_plus_bedroom.value}
    if lead.home_size in high_complexity_sizes or _infer_route_type(lead) == RouteType.interstate.value:
        return MoveComplexity.high.value
    if lead.home_size == HomeSize.two_bedroom.value:
        return MoveComplexity.medium.value
    return MoveComplexity.low.value


def _infer_booking_probability(lead: RawLead) -> int:
    probability = 45
    if lead.urgency == LeadUrgency.same_week.value:
        probability += 25
    elif lead.urgency == LeadUrgency.this_month.value:
        probability += 15
    else:
        probability += 5

    if lead.budget >= 6000:
        probability += 15
    elif lead.budget >= 3000:
        probability += 10
    elif lead.budget < 1000:
        probability -= 15

    if lead.home_size in {HomeSize.three_bedroom.value, HomeSize.four_plus_bedroom.value}:
        probability += 10

    return max(0, min(probability, 100))


def _infer_fraud_risk(lead: RawLead) -> str:
    if lead.budget < 500:
        return RiskLevel.high.value
    if lead.budget < 1200:
        return RiskLevel.medium.value
    return RiskLevel.low.value


def _fallback_response(lead: RawLead | None = None) -> dict:
    if lead is None:
        return {
            "score": 50,
            "reasoning": "AI scoring is temporarily unavailable. Manual review recommended.",
            "booking_probability": 50,
            "estimated_job_value": 0,
            "route_type": RouteType.unknown.value,
            "move_complexity": MoveComplexity.medium.value,
            "fraud_risk": RiskLevel.medium.value,
            "missing_info": [],
            "recommended_followup": "Call the lead to confirm move details and availability.",
            "confidence": 40,
            "best_customer_fit_reason": "Assign to an active customer with available capacity.",
        }

    booking_probability = _infer_booking_probability(lead)
    route_type = _infer_route_type(lead)
    move_complexity = _infer_complexity(lead)
    fraud_risk = _infer_fraud_risk(lead)
    risk_penalty = 20 if fraud_risk == RiskLevel.high.value else 8 if fraud_risk == RiskLevel.medium.value else 0
    score = max(0, min(booking_probability - risk_penalty, 100))

    return {
        "score": score,
        "reasoning": "Lead intelligence was generated with fallback heuristics because AI scoring is temporarily unavailable.",
        "booking_probability": booking_probability,
        "estimated_job_value": lead.budget,
        "route_type": route_type,
        "move_complexity": move_complexity,
        "fraud_risk": fraud_risk,
        "missing_info": [],
        "recommended_followup": "Call quickly to confirm inventory, access constraints, move window, and decision timeline.",
        "confidence": 55,
        "best_customer_fit_reason": "Route based on urgency, job value, move complexity, billing health, and available capacity.",
    }


def normalize_lead_intelligence(lead: RawLead, ai_result: dict) -> dict:
    fallback = _fallback_response(lead)
    normalized = {**fallback, **(ai_result or {})}
    try:
        return ScoredLead(**{**lead.model_dump(mode="json"), **normalized}).model_dump(mode="json")
    except ValidationError:
        logger.exception("AI lead intelligence failed validation; using fallback intelligence.")
        return ScoredLead(**{**lead.model_dump(mode="json"), **fallback}).model_dump(mode="json")


async def analyze_lead(lead: RawLead) -> dict:
    """
    Analyzes a moving lead using OpenAI to return structured lead intelligence.
    """
    prompt = f"""
    You are an expert lead intelligence analyst for a moving lead marketplace.
    Analyze the lead and return marketplace-ready routing signals.

    Lead Details:
    - Name: {lead.full_name}
    - Move Date: {lead.move_date}
    - Origin: {lead.origin_zip}
    - Destination: {lead.destination_zip}
    - Home Size: {lead.home_size}
    - Budget: {lead.budget}
    - Urgency: {lead.urgency}

    Return strictly valid JSON matching the provided schema. Prefer concrete, operational language.
    """

    client = get_openai_client()
    if client is None:
        logger.warning("OPENAI_API_KEY is not configured; using fallback lead scoring.")
        return _fallback_response(lead)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "moving_lead_intelligence",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "score": {"type": "integer", "minimum": 0, "maximum": 100},
                            "reasoning": {"type": "string"},
                            "booking_probability": {"type": "integer", "minimum": 0, "maximum": 100},
                            "estimated_job_value": {"type": "integer", "minimum": 0, "maximum": 100000},
                            "route_type": {
                                "type": "string",
                                "enum": ["local", "intrastate", "interstate", "unknown"],
                            },
                            "move_complexity": {"type": "string", "enum": ["low", "medium", "high"]},
                            "fraud_risk": {"type": "string", "enum": ["low", "medium", "high"]},
                            "missing_info": {"type": "array", "items": {"type": "string"}},
                            "recommended_followup": {"type": "string"},
                            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                            "best_customer_fit_reason": {"type": "string"},
                        },
                        "required": [
                            "score",
                            "reasoning",
                            "booking_probability",
                            "estimated_job_value",
                            "route_type",
                            "move_complexity",
                            "fraud_risk",
                            "missing_info",
                            "recommended_followup",
                            "confidence",
                            "best_customer_fit_reason",
                        ],
                    },
                },
            },
        )
        
        content = response.choices[0].message.content
        return normalize_lead_intelligence(lead, json.loads(content))
    except Exception:
        logger.exception("AI scoring request failed")
        return _fallback_response(lead)
