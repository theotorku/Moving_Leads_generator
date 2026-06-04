from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError
import logging
from ..config import get_settings
from ..models import RawLead, ScoreResponse
from ..services.attribution import first_query_value, normalize_channel
from ..services.ingest_service import map_intake_payload, resolve_api_key
from ..services.rate_limit import FixedWindowRateLimiter
from ..services.scoring_service import score_and_store_lead

router = APIRouter()
logger = logging.getLogger(__name__)

# Public form: per-IP. Partner intake: per-key at 5x (a real integration sends
# more, and it's already credentialed). Limits read from settings at first use.
_public_limiter = FixedWindowRateLimiter(get_settings().rate_limit_per_minute)
_intake_limiter = FixedWindowRateLimiter(get_settings().rate_limit_per_minute * 5)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _derive_attribution(lead_data: dict, request: Request) -> dict:
    """Resolve a browser submission's acquisition attribution from the payload
    fields plus request headers (Referer / landing page query string)."""
    source_url = lead_data.get("source_url") or request.headers.get("referer")
    referrer = lead_data.get("source_referrer") or request.headers.get("referer")
    landing_page = lead_data.get("landing_page") or str(request.url)
    params = parse_qs(urlparse(source_url or landing_page).query)

    utm_source = first_query_value(params, "utm_source", "source", "src", "lead_source")
    utm_medium = first_query_value(params, "utm_medium", "medium")
    utm_campaign = first_query_value(params, "utm_campaign", "campaign")
    partner = first_query_value(params, "partner", "partner_id", "affiliate", "affiliate_id")
    explicit_channel = lead_data.get("source_channel")
    channel = normalize_channel(explicit_channel or utm_source, referrer)

    return {
        "source": channel,
        "source_channel": channel,
        "source_medium": lead_data.get("source_medium") or utm_medium,
        "source_campaign": lead_data.get("source_campaign") or utm_campaign,
        "source_referrer": referrer,
        "source_partner": lead_data.get("source_partner") or partner,
        "source_url": source_url,
        "landing_page": landing_page,
    }


@router.post("/leads/score", response_model=ScoreResponse)
async def score_lead(lead: RawLead, request: Request):
    # Provenance + TCPA consent. source_ip/consent records persist on `leads`,
    # which is RLS-locked to service_role (never exposed to the browser key).
    source_ip = _client_ip(request)
    if not _public_limiter.allow(source_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down and try again shortly.")
    source_fields = _derive_attribution(lead.model_dump(mode="json"), request)
    result = await score_and_store_lead(
        lead, source_fields=source_fields, source_ip=source_ip, verified=False
    )
    return ScoreResponse(
        **result["scored_lead_data"],
        persisted=result["persisted"],
        persistence_warning=result["persistence_warning"],
        calibration=result["calibration"],
    )


@router.post("/leads/intake", response_model=ScoreResponse)
async def intake_lead(
    payload: dict,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """Authenticated inbound lead intake for partners / aggregators / webhooks.

    The API key resolves to a registered source (its channel + partner), which is
    stamped onto the lead — partners can't spoof their own attribution. The lead
    runs the same scoring + persistence pipeline as the public form and is marked
    `verified` (it came from a credentialed source, not an open form)."""
    source = resolve_api_key(x_api_key)
    if not source:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    if not _intake_limiter.allow(source.get("slug") or source.get("id") or "intake"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this source.")

    mapped = map_intake_payload(payload)
    try:
        lead = RawLead(**mapped)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[{"field": e["loc"][-1], "error": e["msg"]} for e in exc.errors()],
        ) from exc

    forwarded = request.headers.get("x-forwarded-for", "")
    source_ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else None
    )
    source_fields = {
        "source": source["channel"],
        "source_channel": source["channel"],
        "source_medium": mapped.get("source_medium"),
        "source_campaign": mapped.get("source_campaign"),
        "source_referrer": None,
        "source_partner": source.get("partner") or source["slug"],
        "source_url": mapped.get("source_url"),
        "landing_page": None,
    }
    result = await score_and_store_lead(
        lead, source_fields=source_fields, source_ip=source_ip, verified=True
    )
    return ScoreResponse(
        **result["scored_lead_data"],
        persisted=result["persisted"],
        persistence_warning=result["persistence_warning"],
        calibration=result["calibration"],
    )
