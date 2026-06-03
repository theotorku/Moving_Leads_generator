from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException, Request
import logging
from ..models import LeadStatus, RawLead, ScoreResponse

router = APIRouter()
logger = logging.getLogger(__name__)

from ..db import get_supabase_client
from ..ai.scorer import analyze_lead, normalize_lead_intelligence
from ..ai.calibration import calibrate


KNOWN_SOURCE_CHANNELS = {
    "direct",
    "organic",
    "google_lsa",
    "google_ads",
    "yelp",
    "angi",
    "thumbtack",
    "realtor_partner",
    "referral_partner",
    "email",
    "social",
    "webhook",
    "manual",
    "unknown",
}


def _first_query_value(params: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        value = params.get(name)
        if value and value[0]:
            return value[0].strip()
    return None


def _normalize_channel(value: str | None, referrer: str | None = None) -> str:
    raw = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "google": "google_ads",
        "googleads": "google_ads",
        "google_ads": "google_ads",
        "adwords": "google_ads",
        "lsa": "google_lsa",
        "google_lsa": "google_lsa",
        "local_services": "google_lsa",
        "local_service_ads": "google_lsa",
        "homeadvisor": "angi",
        "angi": "angi",
        "angie": "angi",
        "thumbtack": "thumbtack",
        "yelp": "yelp",
        "realtor": "realtor_partner",
        "realtor_com": "realtor_partner",
        "real_estate_agent": "realtor_partner",
        "partner": "referral_partner",
        "referral": "referral_partner",
        "facebook": "social",
        "instagram": "social",
        "tiktok": "social",
        "linkedin": "social",
        "email": "email",
        "newsletter": "email",
        "manual": "manual",
        "webhook": "webhook",
        "organic": "organic",
        "direct": "direct",
    }
    if raw in aliases:
        return aliases[raw]
    if raw in KNOWN_SOURCE_CHANNELS:
        return raw

    host = (urlparse(referrer or "").netloc or "").lower()
    if "google." in host:
        return "organic"
    if "yelp." in host:
        return "yelp"
    if "angi." in host or "homeadvisor." in host:
        return "angi"
    if "thumbtack." in host:
        return "thumbtack"
    if "realtor." in host or "zillow." in host:
        return "realtor_partner"
    if referrer:
        return "referral_partner"
    return "direct"


def _derive_attribution(scored_lead_data: dict, request: Request) -> dict:
    source_url = scored_lead_data.get("source_url") or request.headers.get("referer")
    referrer = scored_lead_data.get("source_referrer") or request.headers.get("referer")
    landing_page = scored_lead_data.get("landing_page") or str(request.url)
    params = parse_qs(urlparse(source_url or landing_page).query)

    utm_source = _first_query_value(params, "utm_source", "source", "src", "lead_source")
    utm_medium = _first_query_value(params, "utm_medium", "medium")
    utm_campaign = _first_query_value(params, "utm_campaign", "campaign")
    partner = _first_query_value(params, "partner", "partner_id", "affiliate", "affiliate_id")
    explicit_channel = scored_lead_data.get("source_channel")
    channel = _normalize_channel(explicit_channel or utm_source, referrer)

    return {
        "source": channel,
        "source_channel": channel,
        "source_medium": scored_lead_data.get("source_medium") or utm_medium,
        "source_campaign": scored_lead_data.get("source_campaign") or utm_campaign,
        "source_referrer": referrer,
        "source_partner": scored_lead_data.get("source_partner") or partner,
        "source_url": source_url,
        "landing_page": landing_page,
    }


@router.post("/leads/score", response_model=ScoreResponse)
async def score_lead(lead: RawLead, request: Request):
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

    # Provenance + TCPA consent. source_ip/consent records persist on `leads`,
    # which is RLS-locked to service_role (never exposed to the browser key).
    forwarded = request.headers.get("x-forwarded-for", "")
    source_ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else None
    )
    attribution = _derive_attribution(scored_lead_data, request)
    scored_lead_data.update(attribution)
    consented = bool(scored_lead_data.get("consent_tcpa"))
    stored_lead_data = {
        **scored_lead_data,
        "status": LeadStatus.available.value,
        "source_ip": source_ip,
        "consent_at": datetime.now(timezone.utc).isoformat() if consented else None,
        "verified": False,
    }

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
