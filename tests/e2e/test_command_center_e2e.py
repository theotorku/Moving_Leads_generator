"""Browser E2E for the Command Center "select lead -> recommendation panel" flow.

This is the flow that broke in manual E2E (panel rendered "Failed to fetch") and
that manual testing later confirmed works. The mocked unit tests in test_api.py
lock down the *data contract* of /admin/leads/{id}/assignment-options; this test
locks down the *browser* path on top of it — login, lead selection, and the panel
actually rendering a priority score.

Opt-in and heavyweight (real Supabase + a live server + a headless browser):

    pip install playwright && playwright install chromium
    RUN_E2E=1 python -m pytest tests/e2e -q

Skipped by default and auto-skipped if Playwright or Supabase aren't available, so
the normal suite stays green.
"""
import base64
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_E2E") != "1",
    reason="Set RUN_E2E=1 (Supabase configured + migrations applied + playwright installed) to run browser E2E.",
)

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _client():
    from app.db import get_supabase_client

    try:
        return get_supabase_client()
    except RuntimeError:
        pytest.skip("Supabase is not configured.")


@pytest.fixture
def seeded(request):
    """Seed one assignable buyer + one available lead, run the server, clean up."""
    client = _client()
    marker = uuid.uuid4().hex[:8]

    customer = client.table("customers").insert({
        "company_name": f"E2E Buyer {marker}",
        "email": f"e2e-buyer-{marker}@example.com",
    }).execute().data[0]
    client.table("subscriptions").insert({
        "customer_id": customer["id"], "tier": "starter", "status": "active",
        "leads_included": 30, "leads_used": 0,
    }).execute()
    lead = client.table("leads").insert({
        "full_name": f"E2E Select {marker}", "email": f"e2e-lead-{marker}@example.com",
        "phone": "+1 555-0100", "move_date": "2026-09-01", "origin_zip": "10001",
        "destination_zip": "90210", "home_size": "2_bedroom", "budget": 5000,
        "urgency": "this_month", "score": 80, "reasoning": "e2e",
        "booking_probability": 70, "estimated_job_value": 6000, "route_type": "interstate",
        "move_complexity": "high", "fraud_risk": "low", "confidence": 75,
        "recommended_followup": "call", "best_customer_fit_reason": "fit",
        "status": "available",
    }).execute().data[0]

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(ROOT),
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url, proc)
        yield {"base_url": base_url, "lead": lead, "customer": customer}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        client.table("leads").delete().eq("id", lead["id"]).execute()
        client.table("customers").delete().eq("id", customer["id"]).execute()


def _wait_for_server(base_url: str, proc: subprocess.Popen, timeout: float = 30.0):
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail("uvicorn exited before becoming ready")
        try:
            urllib.request.urlopen(f"{base_url}/", timeout=2)
            return
        except urllib.error.URLError:
            time.sleep(0.3)
    pytest.fail("server did not become ready in time")


def test_select_lead_renders_recommendation_panel(seeded):
    pw = pytest.importorskip("playwright.sync_api")

    from app.config import get_settings

    s = get_settings()
    creds = base64.b64encode(
        f"{s.admin_username}:{s.admin_password.get_secret_value()}".encode()
    ).decode()

    lead_id = seeded["lead"]["id"]
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"Chromium not available: {exc}")
        # Pre-auth so the dashboard's fetches carry admin credentials.
        context = browser.new_context(extra_http_headers={"Authorization": f"Basic {creds}"})
        page = context.new_page()
        page.goto(f"{seeded['base_url']}/admin")

        # The dashboard also has an inline login form; fill it for parity with users.
        if page.locator("#admin-username").is_visible():
            page.fill("#admin-username", s.admin_username)
            page.fill("#admin-password", s.admin_password.get_secret_value())
            page.click("#auth-form button")

        row = page.locator(f'.lead-row[data-lead-id="{lead_id}"]')
        row.wait_for(state="visible", timeout=15000)
        row.click()

        best_score = page.locator("#assignment-panel .best-score")
        best_score.wait_for(state="visible", timeout=15000)
        assert best_score.inner_text().strip().isdigit(), "priority score should render as a number"

        browser.close()
