"""Acquisition-channel normalization shared by the public form route and the
partner intake service. Maps free-form source hints (utm_source, an explicit
channel, or a referrer host) onto the canonical LeadSourceChannel values.
"""
from urllib.parse import urlparse

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

_ALIASES = {
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


def first_query_value(params: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        value = params.get(name)
        if value and value[0]:
            return value[0].strip()
    return None


def normalize_channel(value: str | None, referrer: str | None = None) -> str:
    raw = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in _ALIASES:
        return _ALIASES[raw]
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
