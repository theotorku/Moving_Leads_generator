import logging
from datetime import datetime, timezone

import stripe

from ..config import get_settings

logger = logging.getLogger(__name__)


def _stripe_api_key() -> str | None:
    settings = get_settings()
    if not settings.stripe_secret_key:
        return None
    return settings.stripe_secret_key.get_secret_value()

# Pricing tiers configuration
PRICING_TIERS = {
    "starter": {
        "price": 299,
        "leads_included": 30,
        "overage_price": 12
    },
    "professional": {
        "price": 599,
        "leads_included": 75,
        "overage_price": 10
    },
    "enterprise": {
        "price": 999,
        "leads_included": 150,
        "overage_price": 8
    }
}

ASSIGNABLE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
SUBSCRIPTION_BILLING_MESSAGES = {
    "active": "Subscription is active.",
    "trialing": "Subscription is active during a trial period.",
    "past_due": "Billing is past due. Update payment details before assigning more leads.",
    "unpaid": "Billing is unpaid. Collect payment before assigning more leads.",
    "incomplete": "Subscription setup is incomplete. Finish billing setup before assigning more leads.",
    "paused": "Subscription is paused. Resume billing before assigning more leads.",
    "canceled": "Subscription is canceled. Reactivate billing before assigning more leads.",
    "unknown": "Subscription status could not be verified. Confirm billing before assigning more leads.",
}


def _normalize_timestamp(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def normalize_subscription_status(status: str | None) -> str:
    normalized = (status or "").lower()
    if normalized in SUBSCRIPTION_BILLING_MESSAGES:
        return normalized
    if normalized in {"incomplete_expired", "unpaid"}:
        return "incomplete" if normalized == "incomplete_expired" else "unpaid"
    if normalized in {"paused_collection", "paused"}:
        return "paused"
    return "unknown"


def billing_status_message(status: str | None) -> str:
    return SUBSCRIPTION_BILLING_MESSAGES[normalize_subscription_status(status)]


def can_receive_leads(status: str | None) -> bool:
    return normalize_subscription_status(status) in ASSIGNABLE_SUBSCRIPTION_STATUSES


def sync_subscription_record(supabase, subscription_record: dict) -> dict:
    normalized_status = normalize_subscription_status(subscription_record.get("status"))
    synced_record = {**subscription_record, "status": normalized_status}

    # When webhooks own reconciliation, the DB row is already kept fresh — skip
    # the per-read Stripe API call that otherwise causes N+1 latency on the
    # admin customer list / assignment-options endpoints.
    if get_settings().reconcile_via_webhook:
        return synced_record

    api_key = _stripe_api_key()

    if not api_key or not subscription_record.get("stripe_subscription_id"):
        return synced_record

    try:
        stripe_subscription = stripe.Subscription.retrieve(
            subscription_record["stripe_subscription_id"],
            api_key=api_key,
        )
    except stripe.error.StripeError:
        logger.exception(
            "Stripe subscription sync failed for %s",
            subscription_record.get("stripe_subscription_id"),
        )
        return synced_record
    except Exception:
        logger.exception(
            "Unexpected Stripe subscription sync error for %s",
            subscription_record.get("stripe_subscription_id"),
        )
        return synced_record

    refreshed_status = normalize_subscription_status(stripe_subscription.status)
    refreshed_record = {
        **synced_record,
        "status": refreshed_status,
        "current_period_start": _normalize_timestamp(getattr(stripe_subscription, "current_period_start", None)),
        "current_period_end": _normalize_timestamp(getattr(stripe_subscription, "current_period_end", None)),
    }

    updates = {}
    for field in ("status", "current_period_start", "current_period_end"):
        if refreshed_record.get(field) != synced_record.get(field):
            updates[field] = refreshed_record.get(field)

    if updates and subscription_record.get("id"):
        try:
            supabase.table("subscriptions").update(updates).eq("id", subscription_record["id"]).execute()
        except Exception:
            logger.exception("Failed to persist synced subscription state for %s", subscription_record.get("id"))

    return refreshed_record

async def create_customer(email: str, company_name: str, idempotency_key: str | None = None) -> dict:
    """Create a Stripe customer"""
    try:
        api_key = _stripe_api_key()
        if not api_key:
            logger.warning("Stripe customer creation requested without STRIPE_SECRET_KEY configured.")
            return {"success": False, "error": "Payment provider is not configured."}

        customer = stripe.Customer.create(
            email=email,
            name=company_name,
            api_key=api_key,
            idempotency_key=idempotency_key or f"customer:{email.casefold()}",
        )
        return {"stripe_customer_id": customer.id, "success": True}
    except stripe.error.StripeError:
        logger.exception("Stripe customer creation failed")
        return {"success": False, "error": "Unable to create the customer in Stripe."}
    except Exception:
        logger.exception("Unexpected Stripe customer creation error")
        return {"success": False, "error": "Unexpected payment provider error."}

async def create_subscription(customer_id: str, tier: str, idempotency_key: str | None = None) -> dict:
    """Create a Stripe subscription for a customer"""
    if tier not in PRICING_TIERS:
        return {"success": False, "error": "Invalid tier"}

    try:
        api_key = _stripe_api_key()
        if not api_key:
            logger.warning("Stripe subscription creation requested without STRIPE_SECRET_KEY configured.")
            return {"success": False, "error": "Payment provider is not configured."}

        # In production, you'd create a Stripe Price/Product first
        # For now, we'll use a simple subscription without a product
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{tier.capitalize()} Plan"
                    },
                    "unit_amount": PRICING_TIERS[tier]["price"] * 100,  # Stripe uses cents
                    "recurring": {"interval": "month"}
                }
            }],
            metadata={
                "tier": tier,
                "leads_included": PRICING_TIERS[tier]["leads_included"]
            },
            api_key=api_key,
            idempotency_key=idempotency_key or f"subscription:{customer_id}:{tier}",
        )
        return {
            "success": True,
            "subscription_id": subscription.id,
            "status": subscription.status
        }
    except stripe.error.StripeError:
        logger.exception("Stripe subscription creation failed")
        return {"success": False, "error": "Unable to create the subscription in Stripe."}
    except Exception:
        logger.exception("Unexpected Stripe subscription creation error")
        return {"success": False, "error": "Unexpected payment provider error."}

async def charge_overage(
    customer_id: str, num_leads: int, tier: str, idempotency_key: str | None = None
) -> dict:
    """Charge for overage leads"""
    if tier not in PRICING_TIERS:
        return {"success": False, "error": "Invalid tier"}

    amount = num_leads * PRICING_TIERS[tier]["overage_price"]

    try:
        api_key = _stripe_api_key()
        if not api_key:
            logger.warning("Stripe overage charge requested without STRIPE_SECRET_KEY configured.")
            return {"success": False, "error": "Payment provider is not configured."}

        charge = stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to cents
            currency="usd",
            customer=customer_id,
            description=f"Overage charge for {num_leads} leads",
            metadata={"type": "overage", "num_leads": num_leads},
            api_key=api_key,
            idempotency_key=idempotency_key,
        )
        return {"success": True, "charge_id": charge.id, "amount": amount}
    except stripe.error.StripeError:
        logger.exception("Stripe overage charge failed")
        return {"success": False, "error": "Unable to charge the overage in Stripe."}
    except Exception:
        logger.exception("Unexpected Stripe overage charge error")
        return {"success": False, "error": "Unexpected payment provider error."}


async def cancel_subscription(subscription_id: str | None) -> None:
    """Best-effort cancellation to compensate for a failed registration."""
    api_key = _stripe_api_key()
    if not api_key or not subscription_id:
        return
    try:
        stripe.Subscription.cancel(subscription_id, api_key=api_key)
    except Exception:
        logger.exception("Failed to cancel Stripe subscription %s during cleanup", subscription_id)


async def delete_customer(stripe_customer_id: str | None) -> None:
    """Best-effort deletion to compensate for a failed registration."""
    api_key = _stripe_api_key()
    if not api_key or not stripe_customer_id:
        return
    try:
        stripe.Customer.delete(stripe_customer_id, api_key=api_key)
    except Exception:
        logger.exception("Failed to delete Stripe customer %s during cleanup", stripe_customer_id)
