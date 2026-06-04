"""Browser E2E for the live lead lifecycle.

Two flows, both against a real Supabase + a live server + a headless browser:

1. Command Center "select lead -> recommendation panel" — the flow that once
   rendered "Failed to fetch"; locks down login + lead selection + the panel
   actually rendering a priority score.
2. Public form attribution — submit the public form from a tracked URL
   (utm_source/medium/campaign/partner) and verify the lead shows up in the
   Command Center with the normalized channel + campaign. This is the end-to-end
   check for "where are the leads coming from".

Opt-in and heavyweight:

    pip install playwright && playwright install chromium
    RUN_E2E=1 python -m pytest tests/e2e -q

Skipped by default, and auto-skips (rather than errors) when Playwright isn't
installed or Supabase is unconfigured/unreachable. On failure, a Playwright trace
and full-page screenshot are written to tests/e2e/artifacts/.
"""
import base64
import contextlib
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
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"

# Substrings that mark an exception as a connectivity failure (sandbox/offline)
# rather than a real bug — those should skip, not error.
_CONN_HINTS = (
    "connection", "connect", "timed out", "timeout", "getaddrinfo", "max retries",
    "failed to establish", "network", "name or service", "temporary failure",
    "nodename", "unreachable", "ssl",
)


def _looks_like_conn_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(hint in text for hint in _CONN_HINTS)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _client():
    """Supabase client, or a clean skip if it's unconfigured or unreachable."""
    from app.db import get_supabase_client

    try:
        client = get_supabase_client()
    except RuntimeError:
        pytest.skip("Supabase is not configured.")
    # Probe connectivity so a sandboxed/offline run skips instead of erroring
    # (the failure mode that blocked the first E2E attempt while seeding).
    try:
        client.table("pricing_tiers").select("tier").limit(1).execute()
    except Exception as exc:  # noqa: BLE001 - classify then re-raise non-conn errors
        if _looks_like_conn_error(exc):
            pytest.skip(f"Supabase unreachable: {exc}")
        raise
    return client


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


def _admin_creds() -> str:
    from app.config import get_settings

    s = get_settings()
    return base64.b64encode(
        f"{s.admin_username}:{s.admin_password.get_secret_value()}".encode()
    ).decode()


def _admin_login(page, base_url: str):
    """Open /admin and complete the inline login so dashboard fetches are authed."""
    from app.config import get_settings

    s = get_settings()
    page.goto(f"{base_url}/admin")
    if page.locator("#admin-username").is_visible():
        page.fill("#admin-username", s.admin_username)
        page.fill("#admin-password", s.admin_password.get_secret_value())
        page.click("#auth-form button")


@contextlib.contextmanager
def browser_session(pw, name: str, creds: str | None = None):
    """A traced browser page. On exception, dump a screenshot + trace to artifacts."""
    try:
        browser = pw.chromium.launch()
    except Exception as exc:  # browser binary not installed
        pytest.skip(f"Chromium not available: {exc}")

    ctx_kwargs = {}
    if creds:
        ctx_kwargs["extra_http_headers"] = {"Authorization": f"Basic {creds}"}
    context = browser.new_context(**ctx_kwargs)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    try:
        yield page
    except Exception:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(Exception):
            page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)
        with contextlib.suppress(Exception):
            context.tracing.stop(path=str(ARTIFACTS / f"{name}-trace.zip"))
        raise
    else:
        context.tracing.stop()
    finally:
        browser.close()


@pytest.fixture
def live_server():
    """Run the FastAPI app on a free port for the duration of a test."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(ROOT),
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(base_url, proc)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def seeded(live_server):
    """Seed one assignable buyer + one available lead; clean up and assert nothing lingers."""
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

    try:
        yield {"base_url": live_server, "lead": lead, "customer": customer}
    finally:
        # FK-safe order: lead, subscription, then customer.
        client.table("leads").delete().eq("id", lead["id"]).execute()
        client.table("subscriptions").delete().eq("customer_id", customer["id"]).execute()
        client.table("customers").delete().eq("id", customer["id"]).execute()
        # Cleanup assertion: seeded rows must not linger in Supabase.
        assert not client.table("customers").select("id").eq("id", customer["id"]).execute().data, \
            "E2E customer was not cleaned up"
        assert not client.table("subscriptions").select("id").eq("customer_id", customer["id"]).execute().data, \
            "E2E subscription was not cleaned up"
        assert not client.table("leads").select("id").eq("id", lead["id"]).execute().data, \
            "E2E lead was not cleaned up"


def test_select_lead_renders_recommendation_panel(seeded):
    pw = pytest.importorskip("playwright.sync_api")
    lead_id = seeded["lead"]["id"]

    with pw.sync_playwright() as p:
        with browser_session(p, "select-lead", _admin_creds()) as page:
            _admin_login(page, seeded["base_url"])

            row = page.locator(f'.lead-row[data-lead-id="{lead_id}"]')
            row.wait_for(state="visible", timeout=15000)
            row.click()

            best_score = page.locator("#assignment-panel .best-score")
            best_score.wait_for(state="visible", timeout=15000)
            assert best_score.inner_text().strip().isdigit(), "priority score should render as a number"


def test_public_form_attribution_end_to_end(live_server):
    """Submit the public form from a tracked URL, then confirm the lead shows up
    in the Command Center with the normalized channel + campaign."""
    pw = pytest.importorskip("playwright.sync_api")
    client = _client()

    marker = uuid.uuid4().hex[:8]
    name = f"E2E Form {marker}"
    email = f"e2e-form-{marker}@example.com"
    tracked = "/?utm_source=google_lsa&utm_medium=cpc&utm_campaign=dallas_summer&partner=realtor42"

    try:
        with pw.sync_playwright() as p:
            with browser_session(p, "form-attribution", _admin_creds()) as page:
                # 1) Submit the public form from the tracked landing URL.
                page.goto(f"{live_server}{tracked}")
                page.fill("#full_name", name)
                page.fill("#email", email)
                page.fill("#phone", "+1 555-0123")
                page.fill("#move_date", "2026-09-15")
                page.fill("#origin_zip", "10001")
                page.fill("#destination_zip", "30301")
                page.select_option("#home_size", "2_bedroom")
                page.fill("#budget", "5200")
                page.select_option("#urgency", "this_month")
                page.check("#consent")
                page.click("#submitBtn")
                # AI scoring then persistence; the result card appears on success.
                page.locator("#result").wait_for(state="visible", timeout=60000)

                # 2) Verify in the Command Center: the lead's source cell shows the
                # normalized channel (google_lsa) and the campaign (dallas_summer).
                _admin_login(page, live_server)
                row = page.locator("tr.lead-row", has_text=name)
                row.wait_for(state="visible", timeout=20000)
                row_text = row.inner_text()
                assert "google_lsa" in row_text, f"expected channel google_lsa in row: {row_text!r}"
                assert "dallas_summer" in row_text, f"expected campaign dallas_summer in row: {row_text!r}"

        # Also confirm persistence captured the full attribution server-side.
        saved = client.table("leads").select(
            "source_channel, source_medium, source_campaign, source_partner"
        ).eq("email", email).execute().data
        assert saved, "form lead was not persisted"
        assert saved[0]["source_channel"] == "google_lsa"
        assert saved[0]["source_campaign"] == "dallas_summer"
        assert saved[0]["source_partner"] == "realtor42"
    finally:
        client.table("leads").delete().eq("email", email).execute()
        assert not client.table("leads").select("id").eq("email", email).execute().data, \
            "E2E form lead was not cleaned up"
