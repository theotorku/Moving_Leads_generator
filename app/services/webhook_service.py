"""Stripe webhook reconciliation.

Verifies the webhook signature, records each event idempotently (the
unique(event_id) constraint on stripe_events is the dedupe key), then dispatches
the event to keep our subscriptions / lead_purchases rows in sync with Stripe —
without polling Stripe on every read.
"""
import logging
from datetime import datetime, timezone

import stripe
from fastapi import HTTPException

from ..config import get_settings
from ..db import get_supabase_client
from .stripe_service import _normalize_timestamp, normalize_subscription_status

logger = logging.getLogger(__name__)


def _is_duplicate(exc: Exception) -> bool:
    if getattr(exc, "code", None) == "23505":
        return True
    message = (getattr(exc, "message", None) or str(exc) or "").lower()
    return "duplicate key" in message or "already exists" in message


def _record_event(supabase, event) -> bool:
    """Insert the event row. Returns False if we've already seen this event_id."""
    obj = event["data"]["object"]
    try:
        supabase.table("stripe_events").insert(
            {
                "event_id": event["id"],
                "type": event["type"],
                "status": "received",
                "payload": {
                    "object": obj.get("object"),
                    "object_id": obj.get("id"),
                },
            }
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        if _is_duplicate(exc):
            return False
        raise


def _mark(supabase, event_id: str, status: str, error: str | None = None) -> None:
    try:
        supabase.table("stripe_events").update(
            {
                "status": status,
                "error": error,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("event_id", event_id).execute()
    except Exception:
        logger.exception("Failed to mark Stripe event %s as %s", event_id, status)


def _handle_subscription(supabase, obj, *, deleted: bool) -> str:
    sub_id = obj.get("id")
    if not sub_id:
        return "ignored:no_subscription_id"
    status = "canceled" if deleted else normalize_subscription_status(obj.get("status"))
    supabase.table("subscriptions").update(
        {
            "status": status,
            "current_period_start": _normalize_timestamp(obj.get("current_period_start")),
            "current_period_end": _normalize_timestamp(obj.get("current_period_end")),
        }
    ).eq("stripe_subscription_id", sub_id).execute()
    return f"subscription:{status}"


def _handle_invoice(supabase, obj, event_type: str) -> str:
    sub_id = obj.get("subscription")
    if not sub_id:
        return "ignored:no_subscription"
    status = "active" if event_type.endswith("succeeded") else "past_due"
    supabase.table("subscriptions").update({"status": status}).eq(
        "stripe_subscription_id", sub_id
    ).execute()
    return f"invoice:{status}"


def _handle_payment_intent(supabase, obj, event_type: str) -> str:
    pi_id = obj.get("id")
    if not pi_id:
        return "ignored:no_payment_intent"
    payment_status = "paid" if event_type.endswith("succeeded") else "failed"
    supabase.table("lead_purchases").update({"payment_status": payment_status}).eq(
        "stripe_payment_intent_id", pi_id
    ).execute()
    return f"payment_intent:{payment_status}"


def _handle_refund(supabase, obj) -> str:
    pi_id = obj.get("payment_intent")
    if not pi_id:
        return "ignored:no_payment_intent"
    supabase.table("lead_purchases").update({"payment_status": "refunded"}).eq(
        "stripe_payment_intent_id", pi_id
    ).execute()
    return "payment_intent:refunded"


def _dispatch(supabase, event) -> str:
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type.startswith("customer.subscription."):
        return _handle_subscription(supabase, obj, deleted=event_type.endswith(".deleted"))
    if event_type in ("invoice.payment_succeeded", "invoice.payment_failed"):
        return _handle_invoice(supabase, obj, event_type)
    if event_type in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        return _handle_payment_intent(supabase, obj, event_type)
    if event_type == "charge.refunded":
        return _handle_refund(supabase, obj)
    return "ignored:unhandled_type"


def process_webhook(payload: bytes, sig_header: str | None) -> dict:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret is not configured.")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret.get_secret_value()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload.") from exc
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.") from exc

    try:
        supabase = get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured.") from exc

    # Idempotency: a retried event_id is recorded once and skipped thereafter.
    if not _record_event(supabase, event):
        return {"status": "duplicate", "event_id": event["id"]}

    try:
        outcome = _dispatch(supabase, event)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to handle Stripe event %s", event["id"])
        _mark(supabase, event["id"], "failed", error="handler_error")
        raise HTTPException(status_code=500, detail="Webhook handling failed.") from exc

    final_status = "ignored" if outcome.startswith("ignored") else "processed"
    _mark(supabase, event["id"], final_status)
    return {"status": final_status, "event_id": event["id"], "handled": outcome}
