import logging

from fastapi import HTTPException

from ..db import get_supabase_client
from ..models import LeadStatus
from .stripe_service import (
    PRICING_TIERS,
    billing_status_message,
    can_receive_leads,
    charge_overage,
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


def _lead_intelligence(lead: dict) -> dict:
    return {
        "booking_probability": int(lead.get("booking_probability") or lead.get("score") or 50),
        "estimated_job_value": int(lead.get("estimated_job_value") or lead.get("budget") or 0),
        "route_type": lead.get("route_type") or "unknown",
        "move_complexity": lead.get("move_complexity") or "medium",
        "fraud_risk": lead.get("fraud_risk") or "medium",
        "confidence": int(lead.get("confidence") or 50),
        "recommended_followup": lead.get("recommended_followup")
        or "Call the lead to confirm move details and availability.",
        "best_customer_fit_reason": lead.get("best_customer_fit_reason")
        or "Match with a customer that has active billing and available lead capacity.",
    }


def _tier_fit_score(tier: str, lead: dict) -> int:
    intelligence = _lead_intelligence(lead)
    value = intelligence["estimated_job_value"]
    complexity = intelligence["move_complexity"]
    route_type = intelligence["route_type"]

    if tier == "enterprise":
        score = 86
        if value >= 7000 or complexity == "high" or route_type == "interstate":
            score += 10
    elif tier == "professional":
        score = 82
        if 2500 <= value < 9000 or complexity in {"medium", "high"}:
            score += 8
    else:
        score = 74
        if value < 4000 and complexity in {"low", "medium"} and route_type in {"local", "unknown"}:
            score += 10
        if value >= 8000 or complexity == "high":
            score -= 12

    return max(0, min(score, 100))


def _candidate_priority_score(lead: dict, subscription: dict, remaining: int, projected_price: int, can_assign: bool) -> int:
    intelligence = _lead_intelligence(lead)
    risk_penalty = {"low": 0, "medium": 8, "high": 25}.get(intelligence["fraud_risk"], 10)
    overage_penalty = 6 if projected_price else 0
    capacity_bonus = min(remaining, 10)
    assignability_bonus = 25 if can_assign else -40
    tier_fit = _tier_fit_score(subscription["tier"], lead)

    score = (
        intelligence["booking_probability"] * 0.30
        + intelligence["confidence"] * 0.10
        + tier_fit * 0.35
        + capacity_bonus
        + assignability_bonus
        - risk_penalty
        - overage_penalty
    )
    return max(0, min(round(score), 100))


def _candidate_fit_reason(lead: dict, subscription: dict, remaining: int, projected_price: int, can_assign: bool) -> str:
    intelligence = _lead_intelligence(lead)
    billing_note = billing_status_message(subscription["status"])
    allocation_note = (
        f"{remaining} included leads remain"
        if projected_price == 0
        else f"assignment would be an overage at ${projected_price}"
    )
    readiness = "ready to receive leads" if can_assign else "not assignment-ready"
    return (
        f"{subscription['tier']} plan is {readiness}; {allocation_note}. "
        f"Fit is based on {intelligence['route_type']} route, {intelligence['move_complexity']} complexity, "
        f"${intelligence['estimated_job_value']} estimated value, and {intelligence['fraud_risk']} fraud risk. "
        f"{billing_note}"
    )


def _profile_fit(lead: dict, profile: dict | None) -> dict:
    """Compare a lead against a buyer's routing profile. Empty lists = no limit."""
    profile = profile or {}
    reasons: list[str] = []

    routes = profile.get("accepted_route_types") or []
    route_type = lead.get("route_type") or "unknown"
    if routes and route_type not in routes:
        reasons.append(f"doesn't accept {route_type} moves")

    sizes = profile.get("accepted_home_sizes") or []
    home_size = lead.get("home_size")
    if sizes and home_size and home_size not in sizes:
        reasons.append(f"doesn't service {home_size}")

    min_value = int(profile.get("min_job_value") or 0)
    value = int(lead.get("estimated_job_value") or lead.get("budget") or 0)
    if min_value and value < min_value:
        reasons.append(f"below ${min_value:,} minimum job value")

    zips = profile.get("service_zips") or []
    if zips:
        origin = str(lead.get("origin_zip") or "")
        destination = str(lead.get("destination_zip") or "")
        if not any(origin.startswith(z) or destination.startswith(z) for z in zips):
            reasons.append("outside service area")

    return {"match": not reasons, "reasons": reasons}


def list_leads_for_admin(status: LeadStatus | None = None, min_score: int | None = None) -> dict:
    supabase = _get_supabase()

    try:
        # Embed the purchase so sold leads carry their purchase_id + outcome
        # (the Command Center needs it to drive the feedback loop).
        query = supabase.table("leads").select(
            "*, lead_purchases(id, outcome, price_paid, payment_status, purchase_type, booked_revenue)"
        )
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
        customers = supabase.table("customers").select(
            "*, subscriptions(*), routing_profiles(*)"
        ).execute()
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
            base_score = _candidate_priority_score(
                lead,
                current_subscription,
                remaining,
                recommendations[-1]["projected_price"],
                can_assign,
            )
            fit_reason = _candidate_fit_reason(
                lead,
                current_subscription,
                remaining,
                recommendations[-1]["projected_price"],
                can_assign,
            )

            # Routing profile fit: down-rank mismatches and explain why.
            # routing_profiles is a to-one embed (object or null), not a list.
            rp = customer.get("routing_profiles")
            if isinstance(rp, list):
                rp = rp[0] if rp else {}
            fit = _profile_fit(lead, rp or {})
            recommendations[-1]["profile_match"] = fit["match"]
            recommendations[-1]["profile_reasons"] = fit["reasons"]
            if not fit["match"]:
                base_score = max(0, base_score - 50)
                fit_reason = "⚠ Outside routing profile: " + ", ".join(fit["reasons"]) + ". " + fit_reason
            recommendations[-1]["priority_score"] = base_score
            recommendations[-1]["fit_reason"] = fit_reason

        recommendations.sort(
            key=lambda candidate: (
                not candidate["can_assign"],
                not candidate["profile_match"],
                -candidate["priority_score"],
                -candidate["leads_remaining"],
                candidate["projected_price"] > 0,
                candidate["company_name"].lower(),
            )
        )

        intelligence = _lead_intelligence(lead)
        return {
            "lead": {
                "id": lead["id"],
                "full_name": lead["full_name"],
                "score": lead["score"],
                "status": lead["status"],
                "booking_probability": intelligence["booking_probability"],
                "estimated_job_value": intelligence["estimated_job_value"],
                "route_type": intelligence["route_type"],
                "move_complexity": intelligence["move_complexity"],
                "fraud_risk": intelligence["fraud_risk"],
                "confidence": intelligence["confidence"],
                "recommended_followup": intelligence["recommended_followup"],
                "best_customer_fit_reason": intelligence["best_customer_fit_reason"],
                "source": lead.get("source") or "public_form",
                "source_channel": lead.get("source_channel") or lead.get("source") or "unknown",
                "source_medium": lead.get("source_medium"),
                "source_campaign": lead.get("source_campaign"),
                "source_referrer": lead.get("source_referrer"),
                "source_partner": lead.get("source_partner"),
                "source_url": lead.get("source_url"),
                "landing_page": lead.get("landing_page"),
                "captured_at": lead.get("created_at"),
                "consent_tcpa": bool(lead.get("consent_tcpa")),
            },
            "recommendations": recommendations,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load assignment options for lead %s", lead_id)
        raise HTTPException(status_code=500, detail="Unable to load assignment options.")


def _map_assignment_error(exc: Exception, lead_id: str, customer_id: str) -> "HTTPException":
    """Translate an assign_lead_to_customer() RPC failure into an HTTP error.

    The Postgres function raises stable machine tokens as the error message; the
    unique(lead_id) backstop surfaces as SQLSTATE 23505.
    """
    message = (getattr(exc, "message", None) or str(exc) or "").strip()
    code = getattr(exc, "code", None)

    if "lead_not_found" in message:
        return HTTPException(status_code=404, detail="Lead not found")
    if "no_subscription" in message:
        return HTTPException(status_code=404, detail="No active subscription found")
    if "lead_already_assigned" in message or code == "23505":
        return HTTPException(status_code=409, detail="Lead has already been assigned.")
    if "billing_not_assignable" in message:
        status = message.split("billing_not_assignable:", 1)[1].strip() if ":" in message else None
        return HTTPException(status_code=409, detail=billing_status_message(status))

    logger.exception("Failed to assign lead %s to customer %s", lead_id, customer_id)
    return HTTPException(status_code=500, detail="Unable to assign lead.")


async def _settle_overage_charge(supabase, customer_id: str, result: dict) -> str:
    """Collect an overage charge in Stripe and link it to the purchase row.

    Runs after the lead sale has atomically committed. Returns the resulting
    payment_status. If Stripe is not configured we leave the row 'pending' (the
    reconciliation views surface it); a genuine decline is marked 'failed'.
    The idempotency key makes a retried assignment safe from double-charging.
    """
    purchase_id = result.get("purchase_id")
    if not purchase_id:
        return result.get("payment_status", "pending")

    customer = supabase.table("customers").select("stripe_customer_id").eq("id", customer_id).execute()
    stripe_customer_id = (customer.data or [{}])[0].get("stripe_customer_id")

    tier = None
    if result.get("subscription_id"):
        sub = supabase.table("subscriptions").select("tier").eq("id", result["subscription_id"]).execute()
        tier = (sub.data or [{}])[0].get("tier")

    if not stripe_customer_id or not tier:
        logger.warning("Overage purchase %s left pending: missing Stripe customer or tier", purchase_id)
        return "pending"

    charge = await charge_overage(
        stripe_customer_id, 1, tier, idempotency_key=f"lead_purchase:{purchase_id}"
    )

    if charge.get("success"):
        supabase.table("lead_purchases").update(
            {"stripe_payment_intent_id": charge["charge_id"], "payment_status": "paid"}
        ).eq("id", purchase_id).execute()
        return "paid"

    # Not configured -> stay 'pending' for later collection; real failure -> 'failed'.
    if charge.get("error") == "Payment provider is not configured.":
        return "pending"

    supabase.table("lead_purchases").update({"payment_status": "failed"}).eq("id", purchase_id).execute()
    logger.warning("Overage charge failed for purchase %s: %s", purchase_id, charge.get("error"))
    return "failed"


async def assign_lead_to_customer(
    lead_id: str, customer_id: str, idempotency_key: str | None = None
) -> dict:
    """Sell a lead to a customer atomically via the assign_lead_to_customer RPC.

    The whole sale (mark sold, record purchase, increment usage) runs in one
    Postgres transaction with row locking, so concurrent calls can no longer
    double-sell a lead or lose a usage increment. Pass idempotency_key to make
    client retries safe. Overage sales are then charged in Stripe and the charge
    id is linked back to the purchase row for reconciliation.
    """
    supabase = _get_supabase()

    try:
        response = supabase.rpc(
            "assign_lead_to_customer",
            {
                "p_lead_id": lead_id,
                "p_customer_id": customer_id,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 - mapped to a precise HTTPException
        raise _map_assignment_error(exc, lead_id, customer_id) from exc

    result = response.data or {}
    payment_status = result.get("payment_status")

    if result.get("purchase_type") == "overage" and not result.get("idempotent"):
        payment_status = await _settle_overage_charge(supabase, customer_id, result)

    return {
        "success": True,
        "purchase_type": result.get("purchase_type"),
        "price": result.get("price"),
        "payment_status": payment_status,
        "lead_status": result.get("lead_status", LeadStatus.sold.value),
        "message": result.get("note", "Lead assigned to customer"),
    }


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


def record_lead_outcome(
    purchase_id: str,
    outcome: str,
    booked_revenue: float | None = None,
    dispute_reason: str | None = None,
) -> dict:
    """Advance a sold lead through the funnel (or dispute it) via the RPC."""
    supabase = _get_supabase()
    try:
        response = supabase.rpc(
            "record_lead_outcome",
            {
                "p_purchase_id": purchase_id,
                "p_outcome": outcome,
                "p_booked_revenue": booked_revenue,
                "p_dispute_reason": dispute_reason,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001
        message = (getattr(exc, "message", None) or str(exc) or "").strip()
        if "invalid_outcome" in message:
            raise HTTPException(status_code=400, detail="Invalid outcome.") from exc
        if "purchase_not_found" in message:
            raise HTTPException(status_code=404, detail="Purchase not found.") from exc
        logger.exception("Failed to record lead outcome for purchase %s", purchase_id)
        raise HTTPException(status_code=500, detail="Unable to record outcome.") from exc

    result = response.data or {}
    return {
        "success": True,
        "purchase_id": result.get("purchase_id"),
        "outcome": result.get("outcome"),
        "booked_revenue": result.get("booked_revenue"),
        "payment_status": result.get("payment_status"),
        "message": result.get("note", "Outcome recorded"),
    }


def get_conversion_analytics() -> dict:
    """Funnel + cost-per-booked-move from the conversion_analytics() RPC."""
    supabase = _get_supabase()
    try:
        return (supabase.rpc("conversion_analytics", {}).execute()).data or {}
    except Exception:
        logger.exception("Failed to load conversion analytics")
        raise HTTPException(status_code=500, detail="Unable to load conversion analytics.")


_EMPTY_PROFILE = {
    "service_zips": [], "accepted_route_types": [], "accepted_home_sizes": [],
    "min_job_value": 0, "fmcsa_number": None,
}


def get_routing_profile(customer_id: str) -> dict:
    """Return a customer's routing profile (or empty defaults = no restrictions)."""
    supabase = _get_supabase()
    try:
        res = supabase.table("routing_profiles").select("*").eq("customer_id", customer_id).execute()
    except Exception:
        logger.exception("Failed to load routing profile for %s", customer_id)
        raise HTTPException(status_code=500, detail="Unable to load routing profile.")
    if res.data:
        return res.data[0]
    return {"customer_id": customer_id, **_EMPTY_PROFILE}


def upsert_routing_profile(customer_id: str, profile: dict) -> dict:
    """Create or update a customer's routing profile."""
    supabase = _get_supabase()
    payload = {
        "customer_id": customer_id,
        "service_zips": profile.get("service_zips") or [],
        "accepted_route_types": profile.get("accepted_route_types") or [],
        "accepted_home_sizes": profile.get("accepted_home_sizes") or [],
        "min_job_value": int(profile.get("min_job_value") or 0),
        "fmcsa_number": (profile.get("fmcsa_number") or None),
    }
    try:
        res = supabase.table("routing_profiles").upsert(payload, on_conflict="customer_id").execute()
        return (res.data or [payload])[0]
    except Exception:
        logger.exception("Failed to save routing profile for %s", customer_id)
        raise HTTPException(status_code=500, detail="Unable to save routing profile.")


def get_admin_analytics() -> dict:
    """Return platform analytics from the null-safe admin_analytics() RPC.

    Aggregation happens in Postgres (COALESCE + join to pricing_tiers) so a NULL
    price_paid or an unrecognized tier can no longer crash the endpoint.
    """
    supabase = _get_supabase()

    try:
        response = supabase.rpc("admin_analytics", {}).execute()
        return response.data or {}
    except Exception:
        logger.exception("Failed to load analytics for admin")
        raise HTTPException(status_code=500, detail="Unable to load analytics.")
