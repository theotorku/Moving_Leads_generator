import os
import json
from openai import AsyncOpenAI
from ..models import RawLead

client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
    except Exception as e:
        print(f"AI Scoring Error: {e}")
        # Fallback in case of AI failure
        return {
            "score": 50, 
            "reasoning": "AI scoring failed. Manual review recommended."
        }
