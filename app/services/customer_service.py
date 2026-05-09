import logging

from fastapi import HTTPException

from ..db import get_supabase_client
from ..models import CustomerRegistration
from .stripe_service import PRICING_TIERS, create_customer, create_subscription

logger = logging.getLogger(__name__)


def _get_supabase():
    try:
        return get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured.") from exc


async def register_customer_with_subscription(registration: CustomerRegistration) -> dict:
    stripe_result = await create_customer(registration.email, registration.company_name)
    if not stripe_result["success"]:
        raise HTTPException(status_code=502, detail=stripe_result["error"])

    supabase = _get_supabase()

    try:
        customer_response = supabase.table("customers").insert(
            {
                "company_name": registration.company_name,
                "email": registration.email,
                "phone": registration.phone,
                "stripe_customer_id": stripe_result["stripe_customer_id"],
            }
        ).execute()
        customer_id = customer_response.data[0]["id"]

        subscription_result = await create_subscription(
            stripe_result["stripe_customer_id"],
            registration.tier,
        )
        if not subscription_result["success"]:
            raise HTTPException(status_code=502, detail=subscription_result["error"])

        supabase.table("subscriptions").insert(
            {
                "customer_id": customer_id,
                "tier": registration.tier,
                "status": subscription_result["status"],
                "leads_included": PRICING_TIERS[registration.tier]["leads_included"],
                "leads_used": 0,
                "stripe_subscription_id": subscription_result["subscription_id"],
            }
        ).execute()

        return {
            "success": True,
            "customer_id": customer_id,
            "message": f"Successfully registered with {registration.tier} plan",
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Customer registration failed")
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")


def get_customer_record(customer_id: str) -> dict:
    supabase = _get_supabase()

    try:
        customer = supabase.table("customers").select("*").eq("id", customer_id).execute()
        if not customer.data:
            raise HTTPException(status_code=404, detail="Customer not found")
        return customer.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Customer lookup failed for %s", customer_id)
        raise HTTPException(status_code=500, detail="Unable to load customer details.")


def get_customer_usage_summary(customer_id: str) -> dict:
    supabase = _get_supabase()

    try:
        subscription = (
            supabase.table("subscriptions")
            .select("*")
            .eq("customer_id", customer_id)
            .eq("status", "active")
            .execute()
        )

        if not subscription.data:
            raise HTTPException(status_code=404, detail="No active subscription found")

        current_subscription = subscription.data[0]
        remaining = current_subscription["leads_included"] - current_subscription["leads_used"]

        return {
            "tier": current_subscription["tier"],
            "leads_included": current_subscription["leads_included"],
            "leads_used": current_subscription["leads_used"],
            "leads_remaining": remaining,
            "overage_price": PRICING_TIERS[current_subscription["tier"]]["overage_price"],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Customer usage lookup failed for %s", customer_id)
        raise HTTPException(status_code=500, detail="Unable to load customer usage.")
