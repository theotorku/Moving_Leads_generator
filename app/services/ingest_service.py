"""Partner intake credentials: create / list / revoke / resolve API keys.

Keys are random tokens of the form ``lk_<slug>_<random>``. We persist only the
SHA-256 hash; the plaintext is returned exactly once at creation. Resolving an
inbound key hashes the presentation and looks up the matching active row.
"""
import hashlib
import logging
import re
import secrets

from fastapi import HTTPException

from ..db import get_supabase_client
from .attribution import normalize_channel

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Common partner/aggregator/CSV column names mapped onto our RawLead fields, so
# an inbound payload doesn't have to match our schema exactly.
INTAKE_ALIASES = {
    "name": "full_name", "fullname": "full_name", "customer_name": "full_name",
    "email_address": "email", "emailaddress": "email",
    "phone_number": "phone", "phonenumber": "phone", "tel": "phone", "telephone": "phone",
    "origin": "origin_zip", "from_zip": "origin_zip", "pickup_zip": "origin_zip", "origin_postal": "origin_zip",
    "destination": "destination_zip", "to_zip": "destination_zip", "dropoff_zip": "destination_zip", "destination_postal": "destination_zip",
    "size": "home_size", "home": "home_size", "bedrooms": "home_size",
    "estimated_budget": "budget", "budget_usd": "budget", "price": "budget",
    "timeline": "urgency", "move_urgency": "urgency", "when": "urgency",
    "movedate": "move_date", "date": "move_date",
}


def map_intake_payload(payload: dict) -> dict:
    """Normalize a partner/CSV payload's field names onto RawLead's, light-touch."""
    mapped: dict = {}
    for key, value in (payload or {}).items():
        canonical = INTAKE_ALIASES.get(str(key).strip().lower(), key)
        mapped[canonical] = value
    if isinstance(mapped.get("home_size"), str):
        mapped["home_size"] = mapped["home_size"].strip().lower().replace(" ", "_").replace("-", "_")
    if isinstance(mapped.get("urgency"), str):
        mapped["urgency"] = mapped["urgency"].strip().lower().replace(" ", "_").replace("-", "_")
    if isinstance(mapped.get("budget"), str):
        digits = "".join(ch for ch in mapped["budget"] if ch.isdigit())
        mapped["budget"] = int(digits) if digits else mapped["budget"]
    return mapped


def _get_supabase():
    try:
        return get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured.") from exc


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    return slug or "partner"


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _public_view(row: dict) -> dict:
    """A source row safe to return to the admin UI (never the hash)."""
    return {
        "id": row.get("id"),
        "slug": row.get("slug"),
        "label": row.get("label"),
        "channel": row.get("channel"),
        "partner": row.get("partner"),
        "active": row.get("active", True),
        "created_at": row.get("created_at"),
        "last_used_at": row.get("last_used_at"),
    }


def create_ingest_source(label: str, channel: str | None = None, partner: str | None = None) -> dict:
    """Create a partner source and return its row plus the plaintext key (shown once)."""
    supabase = _get_supabase()
    slug = _slugify(label)
    # Ensure slug uniqueness with a short random suffix if needed.
    plaintext = f"lk_{slug}_{secrets.token_urlsafe(24)}"
    record = {
        "slug": slug,
        "label": label.strip(),
        "channel": normalize_channel(channel) if channel else "webhook",
        "partner": (partner or slug),
        "api_key_hash": _hash_key(plaintext),
        "active": True,
    }
    try:
        inserted = supabase.table("ingest_sources").insert(record).execute().data
    except Exception as exc:
        # Most likely a duplicate slug; make that actionable.
        logger.exception("Failed to create ingest source")
        raise HTTPException(status_code=409, detail="A source with that name already exists; pick another label.") from exc

    row = (inserted or [record])[0]
    out = _public_view(row)
    out["api_key"] = plaintext  # returned once; never stored in plaintext
    return out


def list_ingest_sources() -> list:
    supabase = _get_supabase()
    try:
        rows = supabase.table("ingest_sources").select("*").order("created_at", desc=True).execute().data or []
    except Exception:
        logger.exception("Failed to list ingest sources")
        raise HTTPException(status_code=500, detail="Unable to load intake sources.")
    return [_public_view(r) for r in rows]


def revoke_ingest_source(source_id: str) -> dict:
    supabase = _get_supabase()
    try:
        updated = supabase.table("ingest_sources").update({"active": False}).eq("id", source_id).execute().data
    except Exception:
        logger.exception("Failed to revoke ingest source")
        raise HTTPException(status_code=500, detail="Unable to revoke the intake source.")
    if not updated:
        raise HTTPException(status_code=404, detail="Intake source not found.")
    return _public_view(updated[0])


def resolve_api_key(presented_key: str | None) -> dict | None:
    """Return the active source row for a presented key, or None. Touches last_used_at."""
    if not presented_key:
        return None
    supabase = _get_supabase()
    key_hash = _hash_key(presented_key.strip())
    try:
        rows = (
            supabase.table("ingest_sources")
            .select("*")
            .eq("api_key_hash", key_hash)
            .eq("active", True)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("Failed to resolve intake API key")
        return None
    if not rows:
        return None
    row = rows[0]
    try:
        supabase.table("ingest_sources").update(
            {"last_used_at": "now()"}
        ).eq("id", row["id"]).execute()
    except Exception:
        logger.debug("Could not update last_used_at for ingest source %s", row.get("id"))
    return row
