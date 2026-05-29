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
    assert "AI-powered lead scoring for moving companies" in response.text
    assert '<label for="home_size">Home Size</label>' in response.text


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
        patch("app.routes.leads.analyze_lead", AsyncMock(return_value={"score": 90, "reasoning": "Mocked AI"})),
        patch("app.routes.leads.get_supabase_client", return_value=mock_supabase),
    ):
        response = client.post("/leads/score", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["score"] == 90
    assert data["reasoning"] == "Mocked AI"
    inserted_payload = mock_supabase.table.return_value.insert.call_args.args[0]
    assert inserted_payload["move_date"] == "2026-10-01"
    assert inserted_payload["budget"] == 5000
    assert inserted_payload["status"] == "available"


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
    mock_supabase = MagicMock()
    lead_query = MagicMock()
    lead_query.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "lead-123", "status": "available"}]
    )
    subscription_query = MagicMock()
    subscription_query.eq.return_value.execute.return_value = SimpleNamespace(data=[])
    mock_supabase.table.side_effect = [
        MagicMock(select=MagicMock(return_value=lead_query)),
        MagicMock(select=MagicMock(return_value=subscription_query)),
    ]

    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        response = client.post(
            "/admin/leads/lead-123/assign",
            params={"customer_id": "customer-123"},
            headers=auth_headers(),
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "No active subscription found"}


def test_assign_lead_rejects_sold_lead():
    fake_supabase = FakeSupabase(
        {
            "leads": FakeTable([{"id": "lead-123", "status": "sold"}]),
            "subscriptions": FakeTable([]),
        }
    )

    with patch("app.services.admin_service.get_supabase_client", return_value=fake_supabase):
        response = client.post(
            "/admin/leads/lead-123/assign",
            params={"customer_id": "customer-123"},
            headers=auth_headers(),
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Lead has already been assigned."}


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
