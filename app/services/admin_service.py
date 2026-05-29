import logging

from fastapi import HTTPException

from ..db import get_supabase_client
from ..models import LeadStatus
from .stripe_service import (
    PRICING_TIERS,
    billing_status_message,
    can_receive_leads,
    sync_subscription_record,
)

logger = logging.getLogger(__name__)


def _get_supabase():
    try:
        return get_supabase_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database is not configured.") from exc


def _effective_lead_status(lead: dict) -> str:
    return lead.get("status") or LeadStatus.available.value


def _load_lead(supabase, lead_id: str) -> dict:
    result = supabase.table("leads").select("*").eq("id", lead_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead = result.data[0]
    lead["status"] = _effective_lead_status(lead)
    return lead


def _load_customer_subscription(supabase, customer_id: str) -> dict:
    subscriptions = supabase.table("subscriptions").select("*").eq("customer_id", customer_id).execute()
    if not subscriptions.data:
        raise HTTPException(status_code=404, detail="No active subscription found")

    ranked = sorted(
        subscriptions.data,
        key=lambda subscription: (
            subscription.get("status") in {"active", "trialing"},
            subscription.get("created_at") or "",
        ),
        reverse=True,
    )
    return sync_subscription_record(supabase, ranked[0])


def list_leads_for_admin(status: LeadStatus | None = None, min_score: int | None = None) -> dict:
    supabase = _get_supabase()

    try:
        query = supabase.table("leads").select("*")
        if status:
            query = query.eq("status", status.value)
        if min_score is not None:
            query = query.gte("score", min_score)

        result = query.order("created_at", desc=True).execute()
        leads = [{**lead, "status": _effective_lead_status(lead)} for lead in result.data]
        return {"leads": leads, "count": len(leads)}
    except Exception:
        logger.exception("Failed to list leads for admin")
        raise HTTPException(status_code=500, detail="Unable to load leads.")


def list_lead_assignment_options(lead_id: str) -> dict:
    supabase = _get_supabase()

    try:
        lead = _load_lead(supabase, lead_id)
        customers = supabase.table("customers").select("*, subscriptions(*)").execute()
        recommendations = []

        for customer in customers.data:
            subscriptions = customer.get("subscriptions") or []
            if not subscriptions:
                continue

            current_subscription = sync_subscription_record(
                supabase,
                sorted(
                    subscriptions,
                    key=lambda subscription: (
                        subscription.get("status") in {"active", "trialing"},
                        subscription.get("created_at") or "",
                    ),
                    reverse=True,
                )[0],
            )
            remaining = max(current_subscription["leads_included"] - current_subscription["leads_used"], 0)
            can_assign = can_receive_leads(current_subscription["status"])
            is_overage = current_subscription["leads_used"] >= current_subscription["leads_included"]
            recommendations.append(
                {
                    "customer_id": customer["id"],
                    "company_name": customer["company_name"],
                    "subscription_tier": current_subscription["tier"],
                    "subscription_status": current_subscription["status"],
                    "billing_message": billing_status_message(current_subscription["status"]),
                    "leads_remaining": remaining,
                    "purchase_type": "overage" if is_overage else "included",
                    "projected_price": PRICING_TIERS[current_subscription["tier"]]["overage_price"] if is_overage else 0,
                    "can_assign": can_assign,
                }
            )

        recommendations.sort(
            key=lambda candidate: (
                not candidate["can_assign"],
                candidate["projected_price"] > 0,
                -candidate["leads_remaining"],
                candidate["company_name"].lower(),
            )
        )

        return {
            "lead": {
                "id": lead["id"],
                "full_name": lead["full_name"],
                "score": lead["score"],
                "status": lead["status"],
            },
            "recommendations": recommendations,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load assignment options for lead %s", lead_id)
        raise HTTPException(status_code=500, detail="Unable to load assignment options.")


def assign_lead_to_customer(lead_id: str, customer_id: str) -> dict:
    supabase = _get_supabase()

    try:
        lead = _load_lead(supabase, lead_id)
        if lead["status"] == LeadStatus.sold.value:
            raise HTTPException(status_code=409, detail="Lead has already been assigned.")

        current_subscription = _load_customer_subscription(supabase, customer_id)
        if not can_receive_leads(current_subscription["status"]):
            raise HTTPException(status_code=409, detail=billing_status_message(current_subscription["status"]))

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
            "lead_status": LeadStatus.sold.value,
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
        hydrated_customers = []
        for customer in customers.data:
            subscription = None
            if customer.get("subscriptions"):
                subscription = sync_subscription_record(
                    supabase,
                    sorted(
                        customer["subscriptions"],
                        key=lambda item: (
                            item.get("status") in {"active", "trialing"},
                            item.get("created_at") or "",
                        ),
                        reverse=True,
                    )[0],
                )
            hydrated_customers.append(
                {
                    **customer,
                    "subscriptions": [subscription] if subscription else [],
                    "assignment_ready": can_receive_leads(subscription["status"]) if subscription else False,
                    "billing_message": billing_status_message(subscription["status"]) if subscription else "No subscription found.",
                }
            )

        return {"customers": hydrated_customers, "count": len(hydrated_customers)}
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
        normalized_leads = [{**lead, "status": _effective_lead_status(lead)} for lead in leads.data]
        available_leads = len([lead for lead in normalized_leads if lead["status"] == LeadStatus.available.value])
        sold_leads = len([lead for lead in normalized_leads if lead["status"] == LeadStatus.sold.value])
        overage_revenue = sum(purchase["price_paid"] for purchase in purchases.data)

        return {
            "total_customers": len(customers.data),
            "active_subscriptions": len(active_subs.data),
            "monthly_recurring_revenue": monthly_recurring_revenue,
            "total_leads": len(normalized_leads),
            "available_leads": available_leads,
            "sold_leads": sold_leads,
            "overage_revenue": overage_revenue,
            "total_revenue": monthly_recurring_revenue + overage_revenue,
        }
    except Exception:
        logger.exception("Failed to load analytics for admin")
        raise HTTPException(status_code=500, detail="Unable to load analytics.")
