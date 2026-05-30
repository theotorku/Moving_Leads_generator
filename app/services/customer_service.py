import logging

from fastapi import HTTPException

from ..db import get_supabase_client
from ..models import CustomerRegistration
from .stripe_service import (
    PRICING_TIERS,
    billing_status_message,
    can_receive_leads,
    cancel_subscription,
    create_customer,
    create_subscription,
    delete_customer,
    sync_subscription_record,
)

logger = logging.getLogger(__name__)


def _get_supabase():
    try:
        return get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured.") from exc


def _load_customer(customer_id: str) -> dict:
    customer = _get_supabase().table("customers").select("*").eq("id", customer_id).execute()
    if not customer.data:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer.data[0]


def _pick_current_subscription(subscriptions: list[dict]) -> dict:
    return sorted(
        subscriptions,
        key=lambda subscription: (
            subscription.get("status") in {"active", "trialing"},
            subscription.get("created_at") or "",
        ),
        reverse=True,
    )[0]


def _load_current_subscription(supabase, customer_id: str) -> dict:
    subscriptions = supabase.table("subscriptions").select("*").eq("customer_id", customer_id).execute()
    if not subscriptions.data:
        raise HTTPException(status_code=404, detail="No active subscription found")

    return sync_subscription_record(supabase, _pick_current_subscription(subscriptions.data))


async def _rollback_registration(
    supabase,
    customer_id: str | None,
    stripe_subscription_id: str | None,
    stripe_customer_id: str | None,
) -> None:
    """Undo partial registration so we never leave Stripe and the DB out of sync."""
    if stripe_subscription_id:
        await cancel_subscription(stripe_subscription_id)
    if customer_id:
        try:
            # FK cascade also removes any subscription row written before failure.
            supabase.table("customers").delete().eq("id", customer_id).execute()
        except Exception:
            logger.exception("Failed to remove orphaned customer row %s during cleanup", customer_id)
    if stripe_customer_id:
        await delete_customer(stripe_customer_id)


async def register_customer_with_subscription(registration: CustomerRegistration) -> dict:
    stripe_result = await create_customer(registration.email, registration.company_name)
    if not stripe_result["success"]:
        raise HTTPException(status_code=502, detail=stripe_result["error"])

    stripe_customer_id = stripe_result["stripe_customer_id"]
    supabase = _get_supabase()
    customer_id: str | None = None
    stripe_subscription_id: str | None = None

    try:
        customer_response = supabase.table("customers").insert(
            {
                "company_name": registration.company_name,
                "email": registration.email,
                "phone": registration.phone,
                "stripe_customer_id": stripe_customer_id,
            }
        ).execute()
        customer_id = customer_response.data[0]["id"]

        subscription_result = await create_subscription(stripe_customer_id, registration.tier)
        if not subscription_result["success"]:
            raise HTTPException(status_code=502, detail=subscription_result["error"])
        stripe_subscription_id = subscription_result["subscription_id"]

        supabase.table("subscriptions").insert(
            {
                "customer_id": customer_id,
                "tier": registration.tier,
                "status": subscription_result["status"],
                "leads_included": PRICING_TIERS[registration.tier]["leads_included"],
                "leads_used": 0,
                "stripe_subscription_id": stripe_subscription_id,
            }
        ).execute()

        return {
            "success": True,
            "customer_id": customer_id,
            "message": f"Successfully registered with {registration.tier} plan",
        }
    except Exception as exc:
        await _rollback_registration(supabase, customer_id, stripe_subscription_id, stripe_customer_id)
        if isinstance(exc, HTTPException):
            raise
        logger.exception("Customer registration failed")
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")


def get_customer_record(customer_id: str) -> dict:
    try:
        return _load_customer(customer_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Customer lookup failed for %s", customer_id)
        raise HTTPException(status_code=500, detail="Unable to load customer details.")


def get_customer_usage_summary(customer_id: str) -> dict:
    supabase = _get_supabase()

    try:
        current_subscription = _load_current_subscription(supabase, customer_id)
        remaining = max(current_subscription["leads_included"] - current_subscription["leads_used"], 0)

        return {
            "tier": current_subscription["tier"],
            "status": current_subscription["status"],
            "leads_included": current_subscription["leads_included"],
            "leads_used": current_subscription["leads_used"],
            "leads_remaining": remaining,
            "overage_price": PRICING_TIERS[current_subscription["tier"]]["overage_price"],
            "can_receive_leads": can_receive_leads(current_subscription["status"]),
            "billing_message": billing_status_message(current_subscription["status"]),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Customer usage lookup failed for %s", customer_id)
        raise HTTPException(status_code=500, detail="Unable to load customer usage.")


def get_customer_portal_summary(customer_id: str, email: str) -> dict:
    supabase = _get_supabase()

    try:
        customer = _load_customer(customer_id)
        if customer["email"].casefold() != email.casefold():
            raise HTTPException(status_code=403, detail="Customer ID and email do not match.")

        subscription = _load_current_subscription(supabase, customer_id)
        purchases = supabase.table("lead_purchases").select("*").eq("customer_id", customer_id).execute()
        recent_purchases = sorted(
            purchases.data,
            key=lambda purchase: purchase.get("purchased_at") or "",
            reverse=True,
        )[:10]

        remaining = max(subscription["leads_included"] - subscription["leads_used"], 0)

        return {
            "customer": {
                "id": customer["id"],
                "company_name": customer["company_name"],
                "email": customer["email"],
                "phone": customer.get("phone"),
            },
            "subscription": {
                "tier": subscription["tier"],
                "status": subscription["status"],
                "leads_included": subscription["leads_included"],
                "leads_used": subscription["leads_used"],
                "leads_remaining": remaining,
                "overage_price": PRICING_TIERS[subscription["tier"]]["overage_price"],
                "can_receive_leads": can_receive_leads(subscription["status"]),
                "billing_message": billing_status_message(subscription["status"]),
                "current_period_start": subscription.get("current_period_start"),
                "current_period_end": subscription.get("current_period_end"),
            },
            "recent_purchases": recent_purchases,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Customer portal lookup failed for %s", customer_id)
        raise HTTPException(status_code=500, detail="Unable to load customer portal.")
