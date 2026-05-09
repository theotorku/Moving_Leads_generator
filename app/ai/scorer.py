import json
import logging
from functools import lru_cache

from openai import AsyncOpenAI

from ..config import get_settings
from ..models import RawLead

logger = logging.getLogger(__name__)


@lru_cache
def get_openai_client() -> AsyncOpenAI | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


def _fallback_response() -> dict:
    return {
        "score": 50,
        "reasoning": "AI scoring is temporarily unavailable. Manual review recommended.",
    }

async def analyze_lead(lead: RawLead) -> dict:
    """
    Analyzes a moving lead using OpenAI to determine a quality score (0-100)
    and provides reasoning.
    """
    prompt = f"""
    You are an expert AI lead scorer for the moving industry. 
    Analyze the following lead and assign a score between 0 and 100 based on the likelihood of booking and potential value.
    Provide a brief reasoning for the score.

    Lead Details:
    - Name: {lead.full_name}
    - Move Date: {lead.move_date}
    - Origin: {lead.origin_zip}
    - Destination: {lead.destination_zip}
    - Home Size: {lead.home_size}
    - Budget: {lead.budget}
    - Urgency: {lead.urgency}

    Return your response in strictly valid JSON format like this:
    {{
        "score": 85,
        "reasoning": "High value move (4BR) with immediate urgency, though budget is tight."
    }}
    """

    client = get_openai_client()
    if client is None:
        logger.warning("OPENAI_API_KEY is not configured; using fallback lead scoring.")
        return _fallback_response()

    try:
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo", # or gpt-4 if available/preferred
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        result = json.loads(content)
        return result
    except Exception:
        logger.exception("AI scoring request failed")
        return _fallback_response()
