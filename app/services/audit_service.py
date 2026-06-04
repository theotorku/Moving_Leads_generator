"""Admin action audit trail.

`record_admin_action` is best-effort: it never raises, so a logging hiccup (or an
unconfigured DB) can't break the actual admin action it's recording. Reads go
through the normal client.
"""
import logging

from fastapi import HTTPException

from ..db import get_supabase_client

logger = logging.getLogger(__name__)


def record_admin_action(
    *,
    admin_user: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """Append an entry to admin_audit_log. Swallows all errors by design."""
    try:
        get_supabase_client().table("admin_audit_log").insert({
            "admin_user": admin_user,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "detail": detail,
            "ip": ip,
        }).execute()
    except Exception:
        logger.warning("Could not write admin audit entry for action=%s", action, exc_info=True)


def list_admin_audit(limit: int = 100) -> list:
    """Most-recent admin actions (newest first)."""
    try:
        supabase = get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured.") from exc
    try:
        return (
            supabase.table("admin_audit_log")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("Failed to load admin audit log")
        raise HTTPException(status_code=500, detail="Unable to load the audit log.")
