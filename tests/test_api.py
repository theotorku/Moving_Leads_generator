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
    assert '<label for="home_size">Home size</label>' in response.text


def test_score_lead_endpoint_persists_scored_lead():
    payload = {
        "full_name": "John Doe",
        "email": "john@example.com",
        "phone": "555-123-4567",
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
    select_query = mock_supabase.table.return_value.select.return_value
    select_query.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])

    with patch("app.services.admin_service.get_supabase_client", return_value=mock_supabase):
        response = client.post(
            "/admin/leads/lead-123/assign",
            params={"customer_id": "customer-123"},
            headers=auth_headers(),
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "No active subscription found"}


def test_list_leads_validates_min_score_range():
    response = client.get("/admin/leads?min_score=200", headers=auth_headers())

    assert response.status_code == 422
    assert "less than or equal to 100" in response.text
