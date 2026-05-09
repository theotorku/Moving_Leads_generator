import logging

from fastapi import HTTPException

from ..db import get_supabase_client
from ..models import LeadStatus
from .stripe_service import PRICING_TIERS

logger = logging.getLogger(__name__)


def _get_supabase():
    try:
        return get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured.") from exc


def list_leads_for_admin(status: LeadStatus | None = None, min_score: int | None = None) -> dict:
    supabase = _get_supabase()

    try:
        query = supabase.table("leads").select("*")
        if status:
            query = query.eq("status", status.value)
        if min_score is not None:
            query = query.gte("score", min_score)

        result = query.order("created_at", desc=True).execute()
        return {"leads": result.data, "count": len(result.data)}
    except Exception:
        logger.exception("Failed to list leads for admin")
        raise HTTPException(status_code=500, detail="Unable to load leads.")


def assign_lead_to_customer(lead_id: str, customer_id: str) -> dict:
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
        is_overage = current_subscription["leads_used"] >= current_subscription["leads_included"]
        purchase_type = "overage" if is_overage else "included"
        price = PRICING_TIERS[current_subscription["tier"]]["overage_price"] if is_overage else 0

        supabase.table("leads").update(
            {
                "status": LeadStatus.sold.value,
                "assigned_to": customer_id,
            }
        ).eq("id", lead_id).execute()

        supabase.table("lead_purchases").insert(
            {
                "lead_id": lead_id,
                "customer_id": customer_id,
                "purchase_type": purchase_type,
                "price_paid": price,
            }
        ).execute()

        supabase.table("subscriptions").update(
            {
                "leads_used": current_subscription["leads_used"] + 1,
            }
        ).eq("id", current_subscription["id"]).execute()

        return {
            "success": True,
            "purchase_type": purchase_type,
            "price": price,
            "message": "Lead assigned to customer",
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to assign lead %s to customer %s", lead_id, customer_id)
        raise HTTPException(status_code=500, detail="Unable to assign lead.")


def list_customers_for_admin() -> dict:
    supabase = _get_supabase()

    try:
        customers = supabase.table("customers").select("*, subscriptions(*)").execute()
        return {"customers": customers.data, "count": len(customers.data)}
    except Exception:
        logger.exception("Failed to list customers for admin")
        raise HTTPException(status_code=500, detail="Unable to load customers.")


def get_admin_analytics() -> dict:
    supabase = _get_supabase()

    try:
        customers = supabase.table("customers").select("id").execute()
        active_subs = supabase.table("subscriptions").select("*").eq("status", "active").execute()
        leads = supabase.table("leads").select("id, status").execute()
        purchases = (
            supabase.table("lead_purchases").select("price_paid").eq("purchase_type", "overage").execute()
        )

        monthly_recurring_revenue = sum(PRICING_TIERS[sub["tier"]]["price"] for sub in active_subs.data)
        available_leads = len([lead for lead in leads.data if lead.get("status") == LeadStatus.available.value])
        sold_leads = len([lead for lead in leads.data if lead.get("status") == LeadStatus.sold.value])
        overage_revenue = sum(purchase["price_paid"] for purchase in purchases.data)

        return {
            "total_customers": len(customers.data),
            "active_subscriptions": len(active_subs.data),
            "monthly_recurring_revenue": monthly_recurring_revenue,
            "total_leads": len(leads.data),
            "available_leads": available_leads,
            "sold_leads": sold_leads,
            "overage_revenue": overage_revenue,
            "total_revenue": monthly_recurring_revenue + overage_revenue,
        }
    except Exception:
        logger.exception("Failed to load analytics for admin")
        raise HTTPException(status_code=500, detail="Unable to load analytics.")
