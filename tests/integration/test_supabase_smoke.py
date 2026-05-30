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
