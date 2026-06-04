import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ai.scorer import get_openai_client
from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, get_settings
from app.db import get_supabase_client
from app.main import app

client = TestClient(app)


class FakeTable:
    def __init__(self, data):
        self.data = data
        self.insert_calls = []
        self.update_calls = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def gte(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.insert_calls.append(payload)
        return self

    def update(self, payload):
        self.update_calls.append(payload)
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return self.tables[name]


class FakeAPIError(Exception):
    """Mimics a PostgREST/supabase-py error raised by an RPC call."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code


def _rpc_supabase(*, raises=None, returns=None):
    """A mock supabase client whose .rpc(...).execute() raises or returns data."""
    mock = MagicMock()
    if raises is not None:
        mock.rpc.return_value.execute.side_effect = raises
    else:
        mock.rpc.return_value.execute.return_value = SimpleNamespace(data=returns)
    return mock


@pytest.fixture(autouse=True)
def clear_cached_clients():
    get_settings.cache_clear()
    get_supabase_client.cache_clear()
    get_openai_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_supabase_client.cache_clear()
    get_openai_client.cache_clear()


def auth_headers(
    username: str = DEFAULT_ADMIN_USERNAME,
    password: str = DEFAULT_ADMIN_PASSWORD,
) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_read_main():
    response = client.get("/")

    assert response.status_code == 200
    assert "Moving Leads AI" in response.text
    assert "Score a moving lead" in response.text
    assert '<label for="home_size">Home size</label>' in response.text


def test_score_lead_endpoint_persists_scored_lead():
    payload = {
        "full_name": "John Doe",
        "email": "john@example.com",
        "phone": "+1 (555) 123-4567",
        "move_date": "2026-10-01",
        "origin_zip": "10001",
        "destination_zip": "90210",
        "home_size": "2_bedroom",
        "budget": 5000,
        "urgency": "this_month",
    }

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[])

    with (
        patch(
            "app.services.scoring_service.analyze_lead",
            AsyncMock(
                return_value={
                    "score": 90,
                    "reasoning": "Mocked AI",
                    "booking_probability": 92,
                    "estimated_job_value": 5200,
                    "route_type": "interstate",
                    "move_complexity": "high",
                    "fraud_risk": "low",
                    "missing_info": ["inventory list"],
                    "recommended_followup": "Call within 10 minutes and confirm inventory.",
                    "confidence": 88,
                    "best_customer_fit_reason": "Best for higher-tier movers with interstate capacity.",
                }
            ),
        ),
        patch("app.services.scoring_service.get_supabase_client", return_value=mock_supabase),
    ):
        response = client.post("/leads/score", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["score"] == 90
    assert data["persisted"] is True
    assert data["reasoning"] == "Mocked AI"
    assert data["booking_probability"] == 92
    assert data["route_type"] == "interstate"
    assert data["fraud_risk"] == "low"
    inserted_payload = mock_supabase.table.return_value.insert.call_args.args[0]
    assert inserted_payload["move_date"] == "2026-10-01"
    assert inserted_payload["budget"] == 5000
    assert inserted_payload["status"] == "available"
    assert inserted_payload["estimated_job_value"] == 5200
    assert inserted_payload["recommended_followup"] == "Call within 10 minutes and confirm inventory."


def test_score_lead_surfaces_persistence_failure():
    # A configured insert that errors (e.g. schema drift) must fail loudly (503)
    # instead of masquerading as a successful score.
    payload = {
        "full_name": "John Doe",
        "email": "john@example.com",
        "phone": "+1 (555) 123-4567",
        "move_date": "2026-10-01",
        "origin_zip": "10001",
        "destination_zip": "90210",
        "home_size": "2_bedroom",
        "budget": 5000,
        "urgency": "this_month",
    }

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.side_effect = FakeAPIError(
        "column \"booking_probability\" does not exist"
    )

    with (
        patch("app.services.scoring_service.analyze_lead", AsyncMock(return_value={"score": 90, "reasoning": "Mocked AI"})),
        patch("app.services.scoring_service.get_supabase_client", return_value=mock_supabase),
    ):
        response = client.post("/leads/score", json=payload)

    assert response.status_code == 503


def test_score_lead_captures_consent_and_provenance():
    payload = {
        "full_name": "Consent Lead",
        "email": "consent@example.com",
        "phone": "+1 (555) 123-4567",
        "move_date": "2026-10-01",
        "origin_zip": "10001",
        "destination_zip": "90210",
        "home_size": "2_bedroom",
        "budget": 5000,
        "urgency": "this_month",
        "consent_tcpa": True,
        "consent_text": "I agree to be contacted.",
        "source_url": (
            "https://app.example/lead?"
            "utm_source=google_lsa&utm_medium=cpc&utm_campaign=dallas_summer&partner=realtor42"
        ),
    }

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[])

    with (
        patch("app.services.scoring_service.analyze_lead", AsyncMock(return_value={"score": 88, "reasoning": "ok"})),
        patch("app.services.scoring_service.get_supabase_client", return_value=mock_supabase),
    ):
        response = client.post("/leads/score", json=payload)

    assert response.status_code == 200
    inserted = mock_supabase.table.return_value.insert.call_args.args[0]
    assert inserted["consent_tcpa"] is True
    assert inserted["consent_at"] is not None          # stamped when consented
    assert inserted["source"] == "google_lsa"
    assert inserted["source_channel"] == "google_lsa"
    assert inserted["source_medium"] == "cpc"
    assert inserted["source_campaign"] == "dallas_summer"
    assert inserted["source_partner"] == "realtor42"
    assert inserted["source_ip"]                        # captured server-side
    assert inserted["source_url"].startswith("https://app.example/lead?")
    assert inserted["landing_page"] is not None
    assert response.json()["consent_tcpa"] is True
    assert response.json()["source_channel"] == "google_lsa"


def test_score_lead_accepts_blank_source_fields_from_public_form():
    payload = {
        "full_name": "Direct Lead",
        "email": "direct@example.com",
        "phone": "+1 (555) 123-4567",
        "move_date": "2026-10-01",
        "origin_zip": "10001",
        "destination_zip": "90210",
        "home_size": "2_bedroom",
        "budget": 5000,
        "urgency": "this_month",
        "source_channel": "",
        "source_medium": "",
        "source_campaign": "",
        "source_partner": "",
        "source_referrer": "",
    }

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[])

    with (
        patch("app.services.scoring_service.analyze_lead", AsyncMock(return_value={"score": 80, "reasoning": "ok"})),
        patch("app.services.scoring_service.get_supabase_client", return_value=mock_supabase),
    ):
        response = client.post("/leads/score", json=payload)

    assert response.status_code == 200
    inserted = mock_supabase.table.return_value.insert.call_args.args[0]
    assert inserted["source"] == "direct"
    assert inserted["source_channel"] == "direct"


def test_register_customer_rejects_invalid_tier():
    response = client.post(
        "/customers/register",
        json={
            "company_name": "Acme Moving",
            "email": "ops@acme.example",
            "phone": "555-222-3333",
            "tier": "gold",
        },
    )

    assert response.status_code == 422
    assert "Input should be 'starter', 'professional' or 'enterprise'" in response.text


def test_get_customer_not_found_returns_404():
    mock_supabase = MagicMock()
    select_query = mock_supabase.table.return_value.select.return_value
    select_query.eq.return_value.execute.return_value = SimpleNamespace(data=[])

    with patch("app.services.customer_service.get_supabase_client", return_value=mock_supabase):
        response = client.get("/customers/customer-123")

    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}


def test_assign_lead_preserves_404_for_missing_subscription():
    # The assign RPC raises 'no_subscription'; the service must map it to 404.
    mock_supabase = _rpc_supabase(raises=FakeAPIError("no_subscription"))

    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        response = client.post(
            "/admin/leads/lead-123/assign",
            params={"customer_id": "customer-123"},
            headers=auth_headers(),
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "No active subscription found"}


def test_assign_lead_rejects_sold_lead():
    # The assign RPC raises 'lead_already_assigned' for an already-sold lead.
    mock_supabase = _rpc_supabase(raises=FakeAPIError("lead_already_assigned"))

    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        response = client.post(
            "/admin/leads/lead-123/assign",
            params={"customer_id": "customer-123"},
            headers=auth_headers(),
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Lead has already been assigned."}


def test_assign_lead_double_sell_backstop_maps_to_409():
    # The unique(lead_id) constraint surfaces as SQLSTATE 23505 -> 409.
    mock_supabase = _rpc_supabase(raises=FakeAPIError("duplicate key value", code="23505"))

    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        response = client.post(
            "/admin/leads/lead-123/assign",
            params={"customer_id": "customer-123"},
            headers=auth_headers(),
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Lead has already been assigned."}


def test_assign_lead_included_returns_success():
    mock_supabase = _rpc_supabase(
        returns={
            "success": True,
            "purchase_type": "included",
            "price": 0,
            "payment_status": "recorded",
            "lead_status": "sold",
            "note": "Lead assigned to customer",
            "purchase_id": "purchase-1",
        }
    )

    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        response = client.post(
            "/admin/leads/lead-123/assign",
            params={"customer_id": "customer-123"},
            headers=auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["purchase_type"] == "included"
    assert body["lead_status"] == "sold"
    # Included assignment must not attempt a Stripe charge.
    mock_supabase.rpc.assert_called_once()


def test_assignment_options_rank_assignable_customers_first():
    fake_supabase = FakeSupabase(
        {
            "leads": FakeTable([{"id": "lead-123", "full_name": "John Doe", "score": 88, "status": "available"}]),
            "customers": FakeTable(
                [
                    {
                        "id": "customer-1",
                        "company_name": "Ready Movers",
                        "subscriptions": [
                            {
                                "id": "sub-1",
                                "tier": "starter",
                                "status": "active",
                                "leads_included": 30,
                                "leads_used": 10,
                            }
                        ],
                    },
                    {
                        "id": "customer-2",
                        "company_name": "Billing Hold Movers",
                        "subscriptions": [
                            {
                                "id": "sub-2",
                                "tier": "professional",
                                "status": "past_due",
                                "leads_included": 75,
                                "leads_used": 5,
                            }
                        ],
                    },
                ]
            ),
            "subscriptions": FakeTable([]),
        }
    )

    with patch("app.services.admin_service.get_supabase_client", return_value=fake_supabase):
        response = client.get("/admin/leads/lead-123/assignment-options", headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommendations"][0]["customer_id"] == "customer-1"
    assert payload["recommendations"][0]["can_assign"] is True
    assert payload["recommendations"][1]["customer_id"] == "customer-2"
    assert payload["recommendations"][1]["can_assign"] is False


def test_assignment_options_use_lead_intelligence_for_priority():
    fake_supabase = FakeSupabase(
        {
            "leads": FakeTable(
                [
                    {
                        "id": "lead-456",
                        "full_name": "Jane Smith",
                        "score": 91,
                        "status": "available",
                        "booking_probability": 94,
                        "estimated_job_value": 12000,
                        "route_type": "interstate",
                        "move_complexity": "high",
                        "fraud_risk": "low",
                        "confidence": 90,
                        "recommended_followup": "Confirm interstate availability and packing scope.",
                        "best_customer_fit_reason": "High-value interstate lead should go to an advanced buyer.",
                    }
                ]
            ),
            "customers": FakeTable(
                [
                    {
                        "id": "starter-customer",
                        "company_name": "Starter Local Movers",
                        "subscriptions": [
                            {
                                "id": "sub-starter",
                                "tier": "starter",
                                "status": "active",
                                "leads_included": 30,
                                "leads_used": 1,
                            }
                        ],
                    },
                    {
                        "id": "enterprise-customer",
                        "company_name": "Enterprise Van Lines",
                        "subscriptions": [
                            {
                                "id": "sub-enterprise",
                                "tier": "enterprise",
                                "status": "active",
                                "leads_included": 150,
                                "leads_used": 145,
                            }
                        ],
                    },
                ]
            ),
            "subscriptions": FakeTable([]),
        }
    )

    with patch("app.services.admin_service.get_supabase_client", return_value=fake_supabase):
        response = client.get("/admin/leads/lead-456/assignment-options", headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["lead"]["booking_probability"] == 94
    assert payload["lead"]["recommended_followup"] == "Confirm interstate availability and packing scope."
    assert payload["recommendations"][0]["customer_id"] == "enterprise-customer"
    assert payload["recommendations"][0]["priority_score"] > payload["recommendations"][1]["priority_score"]
    assert "interstate route" in payload["recommendations"][0]["fit_reason"]


def test_list_leads_validates_min_score_range():
    response = client.get("/admin/leads?min_score=200", headers=auth_headers())

    assert response.status_code == 422
    assert "less than or equal to 100" in response.text


def test_customer_portal_requires_matching_email():
    fake_supabase = FakeSupabase(
        {
            "customers": FakeTable(
                [
                    {
                        "id": "customer-123",
                        "company_name": "Acme Moving",
                        "email": "ops@acme.example",
                    }
                ]
            ),
            "subscriptions": FakeTable([]),
            "lead_purchases": FakeTable([]),
        }
    )

    with patch("app.services.customer_service.get_supabase_client", return_value=fake_supabase):
        response = client.get(
            "/customers/portal/access",
            params={"customer_id": "customer-123", "email": "wrong@example.com"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Customer ID and email do not match."}


def test_customer_portal_returns_subscription_summary():
    fake_supabase = FakeSupabase(
        {
            "customers": FakeTable(
                [
                    {
                        "id": "customer-123",
                        "company_name": "Acme Moving",
                        "email": "ops@acme.example",
                        "phone": "555-222-3333",
                    }
                ]
            ),
            "subscriptions": FakeTable(
                [
                    {
                        "id": "sub-123",
                        "customer_id": "customer-123",
                        "tier": "starter",
                        "status": "past_due",
                        "leads_included": 30,
                        "leads_used": 28,
                    }
                ]
            ),
            "lead_purchases": FakeTable(
                [
                    {
                        "lead_id": "lead-1",
                        "purchase_type": "included",
                        "price_paid": 0,
                        "purchased_at": "2026-01-01T10:00:00Z",
                    }
                ]
            ),
        }
    )

    with patch("app.services.customer_service.get_supabase_client", return_value=fake_supabase):
        response = client.get(
            "/customers/portal/access",
            params={"customer_id": "customer-123", "email": "ops@acme.example"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["customer"]["company_name"] == "Acme Moving"
    assert payload["subscription"]["status"] == "past_due"
    assert payload["subscription"]["leads_remaining"] == 2
    assert payload["subscription"]["can_receive_leads"] is False
    assert payload["recent_purchases"][0]["lead_id"] == "lead-1"


def test_customer_portal_page_is_served():
    response = client.get("/portal")

    assert response.status_code == 200
    assert "Customer Portal" in response.text


# --- Outcome feedback loop ---------------------------------------------------

def test_record_lead_outcome_booked():
    mock_supabase = _rpc_supabase(returns={
        "success": True, "purchase_id": "p-1", "outcome": "booked",
        "booked_revenue": 2400, "payment_status": "recorded", "note": "Outcome recorded",
    })
    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        res = client.post(
            "/admin/purchases/p-1/outcome?outcome=booked&booked_revenue=2400",
            headers=auth_headers(),
        )
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"] == "booked"
    assert body["booked_revenue"] == 2400


def test_record_lead_outcome_invalid_maps_to_400():
    mock_supabase = _rpc_supabase(raises=FakeAPIError("invalid_outcome:foo"))
    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        res = client.post("/admin/purchases/p-1/outcome?outcome=foo", headers=auth_headers())
    assert res.status_code == 400


def test_conversion_analytics_endpoint():
    mock_supabase = _rpc_supabase(returns={
        "sold": 2, "contacted": 2, "appointment": 1, "booked": 1,
        "lost": 0, "disputed": 0, "booked_revenue": 2400,
        "lead_spend": 12, "cost_per_booked_move": 12.0, "book_rate": 50.0,
    })
    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        res = client.get("/admin/conversion", headers=auth_headers())
    assert res.status_code == 200
    body = res.json()
    assert body["booked"] == 1
    assert body["cost_per_booked_move"] == 12.0


def test_lead_sources_endpoint():
    mock_supabase = _rpc_supabase(returns=[
        {"channel": "google_ads", "leads": 42, "avg_score": 78, "avg_booking_probability": 70,
         "sold": 12, "booked": 8, "disputed": 1, "revenue": 1840, "booked_revenue": 24000, "book_rate": 19.0},
        {"channel": "direct", "leads": 7, "avg_score": 81, "avg_booking_probability": 75,
         "sold": 0, "booked": 0, "disputed": 0, "revenue": 0, "booked_revenue": 0, "book_rate": 0.0},
    ])
    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        res = client.get("/admin/sources", headers=auth_headers())
    assert res.status_code == 200
    sources = res.json()["sources"]
    assert sources[0]["channel"] == "google_ads"
    assert sources[0]["leads"] == 42
    assert sources[0]["book_rate"] == 19.0


def test_lead_sources_requires_admin():
    assert client.get("/admin/sources").status_code == 401


# --- Phase D: partner intake + CSV import -----------------------------------

def test_intake_requires_api_key():
    assert client.post("/leads/intake", json={"full_name": "A"}).status_code == 401


def test_intake_rejects_unknown_key():
    with patch("app.routes.leads.resolve_api_key", return_value=None):
        res = client.post("/leads/intake", json={"full_name": "A"}, headers={"X-API-Key": "bad"})
    assert res.status_code == 401


def test_intake_scores_and_stamps_source_from_key():
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[])
    # Partner-style payload: aliased field names + messy formats.
    payload = {
        "name": "Partner Lead", "email": "partner-lead@example.com", "tel": "+1 555 0100",
        "move_date": "2026-10-01", "origin": "10001", "destination": "90210",
        "size": "2 bedroom", "budget": "$4,500", "timeline": "this month",
        "consent_tcpa": True,
    }
    with (
        patch("app.routes.leads.resolve_api_key",
              return_value={"slug": "acme", "channel": "referral_partner", "partner": "acme"}),
        patch("app.services.scoring_service.analyze_lead",
              AsyncMock(return_value={"score": 77, "reasoning": "ok"})),
        patch("app.services.scoring_service.get_supabase_client", return_value=mock_supabase),
    ):
        res = client.post("/leads/intake", json=payload, headers={"X-API-Key": "lk_acme_x"})
    assert res.status_code == 200
    inserted = mock_supabase.table.return_value.insert.call_args.args[0]
    assert inserted["source_channel"] == "referral_partner"   # from the key, not the payload
    assert inserted["source_partner"] == "acme"
    assert inserted["verified"] is True
    assert inserted["origin_zip"] == "10001"                  # mapped from "origin"
    assert inserted["budget"] == 4500                         # coerced from "$4,500"


def test_intake_invalid_payload_returns_422():
    with patch("app.routes.leads.resolve_api_key",
               return_value={"slug": "acme", "channel": "webhook", "partner": "acme"}):
        res = client.post("/leads/intake", json={"full_name": "x"}, headers={"X-API-Key": "lk_x"})
    assert res.status_code == 422


def test_create_ingest_source_returns_key_once():
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "s-1", "slug": "acme-movers", "label": "Acme Movers",
               "channel": "referral_partner", "partner": "acme-movers", "active": True,
               "created_at": None, "last_used_at": None}])
    with patch("app.services.ingest_service.get_supabase_client", return_value=mock_supabase):
        res = client.post("/admin/ingest-sources",
                          json={"label": "Acme Movers", "channel": "referral_partner"},
                          headers=auth_headers())
    assert res.status_code == 201
    body = res.json()
    assert body["api_key"].startswith("lk_")       # plaintext shown once
    assert "api_key_hash" not in body              # never the hash
    # The stored record carries only the hash.
    stored = mock_supabase.table.return_value.insert.call_args.args[0]
    assert "api_key_hash" in stored and "api_key" not in stored


def test_ingest_sources_require_admin():
    assert client.get("/admin/ingest-sources").status_code == 401
    assert client.post("/admin/ingest-sources", json={"label": "X"}).status_code == 401


def test_csv_import_scores_rows_and_reports_skips():
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[])
    csv_content = (
        "full_name,email,phone,move_date,origin_zip,destination_zip,home_size,budget,urgency\n"
        "Csv One,csv1@example.com,5550100,2026-10-01,10001,90210,2_bedroom,4000,this_month\n"
        "Bad Row,not-an-email,,,,,,,\n"
    )
    with (
        patch("app.services.scoring_service.analyze_lead",
              AsyncMock(return_value={"score": 70, "reasoning": "ok"})),
        patch("app.services.scoring_service.get_supabase_client", return_value=mock_supabase),
    ):
        res = client.post(
            "/admin/leads/import",
            files={"file": ("leads.csv", csv_content, "text/csv")},
            data={"channel": "manual"},
            headers=auth_headers(),
        )
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == 1
    assert len(body["skipped"]) >= 1               # the bad row


def test_csv_import_requires_admin():
    res = client.post("/admin/leads/import",
                      files={"file": ("x.csv", "a,b\n1,2\n", "text/csv")})
    assert res.status_code == 401


# --- Stripe webhook reconciliation ------------------------------------------

import stripe  # noqa: E402

from app.services import webhook_service  # noqa: E402


class _FakeWebhookSettings:
    def __init__(self, secret="whsec_test"):
        self.stripe_webhook_secret = (
            SimpleNamespace(get_secret_value=lambda: secret) if secret else None
        )


class RaisingInsertTable(FakeTable):
    def execute(self):
        raise FakeAPIError("duplicate key value violates unique constraint", code="23505")


def _fake_event(event_id, event_type, obj):
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def test_webhook_rejects_invalid_signature():
    with patch.object(webhook_service, "get_settings", return_value=_FakeWebhookSettings()), patch.object(
        stripe.Webhook,
        "construct_event",
        side_effect=stripe.error.SignatureVerificationError("bad sig", "sig-header"),
    ):
        response = client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "bad"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid webhook signature."}


def test_webhook_requires_configured_secret():
    with patch.object(webhook_service, "get_settings", return_value=_FakeWebhookSettings(secret=None)):
        response = client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"})

    assert response.status_code == 503


def test_webhook_is_idempotent_on_duplicate_event():
    event = _fake_event("evt_dup", "payment_intent.succeeded", {"id": "pi_1", "object": "payment_intent"})
    fake_supabase = FakeSupabase({"stripe_events": RaisingInsertTable([])})

    with patch.object(webhook_service, "get_settings", return_value=_FakeWebhookSettings()), patch.object(
        stripe.Webhook, "construct_event", return_value=event
    ), patch.object(webhook_service, "get_supabase_client", return_value=fake_supabase):
        response = client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "ok"})

    assert response.status_code == 200
    assert response.json() == {"status": "duplicate", "event_id": "evt_dup"}


def test_webhook_updates_subscription_status():
    event = _fake_event(
        "evt_sub",
        "customer.subscription.updated",
        {"id": "sub_1", "status": "past_due", "current_period_start": None, "current_period_end": None},
    )
    subscriptions = FakeTable([])
    fake_supabase = FakeSupabase({"stripe_events": FakeTable([]), "subscriptions": subscriptions})

    with patch.object(webhook_service, "get_settings", return_value=_FakeWebhookSettings()), patch.object(
        stripe.Webhook, "construct_event", return_value=event
    ), patch.object(webhook_service, "get_supabase_client", return_value=fake_supabase):
        response = client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "ok"})

    assert response.status_code == 200
    assert response.json()["handled"] == "subscription:past_due"
    assert {"status": "past_due", "current_period_start": None, "current_period_end": None} in subscriptions.update_calls


def test_webhook_links_payment_intent_to_purchase():
    event = _fake_event("evt_pi", "payment_intent.succeeded", {"id": "pi_42", "object": "payment_intent"})
    purchases = FakeTable([])
    fake_supabase = FakeSupabase({"stripe_events": FakeTable([]), "lead_purchases": purchases})

    with patch.object(webhook_service, "get_settings", return_value=_FakeWebhookSettings()), patch.object(
        stripe.Webhook, "construct_event", return_value=event
    ), patch.object(webhook_service, "get_supabase_client", return_value=fake_supabase):
        response = client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "ok"})

    assert response.status_code == 200
    assert response.json()["handled"] == "payment_intent:paid"
    assert {"payment_status": "paid"} in purchases.update_calls
