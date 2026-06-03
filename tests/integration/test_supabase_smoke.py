"""DB-backed smoke tests that run against a REAL Supabase project.

These exist because the mocked unit tests can't catch schema drift — exactly the
gap that let the live `leads` table fall behind the backend (missing AI columns)
and the `admin_analytics()` RPC go missing.

Opt-in: set RUN_SUPABASE_IT=1 with Supabase env configured AND the migrations in
supabase/migrations/ applied. Skipped by default so the normal suite stays green.

    RUN_SUPABASE_IT=1 python -m pytest tests/integration -q
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SUPABASE_IT") != "1",
    reason="Set RUN_SUPABASE_IT=1 (Supabase configured + migrations applied) to run live DB tests.",
)


def _client():
    from app.db import get_supabase_client

    try:
        return get_supabase_client()
    except RuntimeError:
        pytest.skip("Supabase is not configured.")


def test_admin_analytics_rpc_returns_expected_shape():
    client = _client()
    result = client.rpc("admin_analytics", {}).execute()
    data = result.data
    assert isinstance(data, dict), "admin_analytics() should return a JSON object"
    for key in (
        "total_customers",
        "active_subscriptions",
        "trialing_subscriptions",
        "active_or_trialing_subscriptions",
        "monthly_recurring_revenue",
        "total_leads",
        "available_leads",
        "sold_leads",
        "overage_revenue",
        "total_revenue",
    ):
        assert key in data, f"admin_analytics() missing key: {key}"


def test_leads_table_accepts_intelligence_columns():
    """Insert a fully-populated lead, then clean it up.

    Fails loudly if the live `leads` table is missing AI-intelligence columns —
    the schema-drift bug surfaced in E2E.
    """
    client = _client()
    marker_email = f"it-{uuid.uuid4().hex}@example.com"
    row = {
        "full_name": "Integration Smoke",
        "email": marker_email,
        "phone": "+1 555-0100",
        "move_date": "2026-09-01",
        "origin_zip": "10001",
        "destination_zip": "90210",
        "home_size": "2_bedroom",
        "budget": 5000,
        "urgency": "this_month",
        "score": 80,
        "reasoning": "integration smoke",
        "booking_probability": 70,
        "estimated_job_value": 6000,
        "route_type": "interstate",
        "move_complexity": "high",
        "fraud_risk": "low",
        "missing_info": [],
        "recommended_followup": "call",
        "confidence": 75,
        "best_customer_fit_reason": "fit",
        "status": "available",
    }

    inserted = client.table("leads").insert(row).execute()
    try:
        assert inserted.data, "insert returned no row"
    finally:
        client.table("leads").delete().eq("email", marker_email).execute()


def test_assignment_options_returns_recommendations():
    """Command Center lead-selection path: selecting a lead must return buyer
    recommendations with the fields the side panel renders. Reproduces the flow
    that failed in browser E2E (panel "Failed to fetch").
    """
    import base64

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    client = _client()
    marker = uuid.uuid4().hex[:8]

    customer = client.table("customers").insert({
        "company_name": f"IT Buyer {marker}",
        "email": f"it-buyer-{marker}@example.com",
    }).execute().data[0]
    client.table("subscriptions").insert({
        "customer_id": customer["id"], "tier": "starter", "status": "active",
        "leads_included": 30, "leads_used": 0,
    }).execute()
    lead = client.table("leads").insert({
        "full_name": "IT Assign Lead", "email": f"it-assign-{marker}@example.com",
        "phone": "+1 555-0100", "move_date": "2026-09-01", "origin_zip": "10001",
        "destination_zip": "90210", "home_size": "2_bedroom", "budget": 5000,
        "urgency": "this_month", "score": 80, "reasoning": "it", "status": "available",
    }).execute().data[0]

    s = get_settings()
    auth = "Basic " + base64.b64encode(
        f"{s.admin_username}:{s.admin_password.get_secret_value()}".encode()
    ).decode()

    try:
        api = TestClient(app)
        res = api.get(
            f"/admin/leads/{lead['id']}/assignment-options",
            headers={"Authorization": auth},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["lead"]["id"] == lead["id"]
        best = next(r for r in data["recommendations"] if r["customer_id"] == customer["id"])
        for key in ("priority_score", "projected_price", "purchase_type", "can_assign", "fit_reason"):
            assert key in best, f"recommendation missing {key}"
        assert best["can_assign"] is True
    finally:
        client.table("leads").delete().eq("id", lead["id"]).execute()
        client.table("customers").delete().eq("id", customer["id"]).execute()
