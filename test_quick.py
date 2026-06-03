"""
Quick diagnostic for the setup. Doubles as pytest smoke tests.

The ``test_*`` functions use assertions (so pytest treats them as real tests and
does not warn about returned values). Environment-dependent checks (database)
degrade gracefully instead of failing when nothing is configured.
"""

import sys
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))


def test_imports():
    """All required modules can be imported."""
    import fastapi  # noqa: F401
    import openai  # noqa: F401
    import pydantic  # noqa: F401
    import uvicorn  # noqa: F401
    from supabase import create_client  # noqa: F401


def test_config():
    """Configuration loads and exposes the expected fields."""
    from app.config import get_settings

    settings = get_settings()
    assert isinstance(settings.admin_username, str)
    assert settings.admin_username  # always set (defaults to "admin")


def test_models():
    """Pydantic lead models construct correctly."""
    from datetime import date

    from app.models import RawLead, ScoredLead

    lead = RawLead(
        full_name="Test User",
        email="test@example.com",
        phone="+1 555-0100",
        move_date=date(2026, 6, 15),
        origin_zip="10001",
        destination_zip="90210",
        home_size="2_bedroom",
        budget=5000,
        urgency="this_month",
    )
    scored = ScoredLead(**lead.model_dump(), score=85, reasoning="Test reasoning")
    assert scored.score == 85
    assert scored.full_name == "Test User"


def test_database():
    """Supabase client constructs when configured; otherwise nothing to assert."""
    from app.db import get_supabase_client

    try:
        client = get_supabase_client()
    except RuntimeError:
        # Not configured in this environment — a valid degraded state.
        return
    assert client is not None


def test_api_routes():
    """The core routes are registered on the app."""
    from app.main import app

    routes = [route.path for route in app.routes]
    for expected in ("/", "/admin", "/portal", "/leads/score"):
        assert expected in routes or any(r.startswith(expected) for r in routes), (
            f"missing route: {expected}"
        )


def main():
    """Run the checks as a CLI diagnostic (prints PASS/FAIL per check)."""
    print("=" * 60)
    print("Moving Leads AI - Quick Test")
    print("=" * 60)

    checks = [
        ("Imports", test_imports),
        ("Configuration", test_config),
        ("Models", test_models),
        ("Database", test_database),
        ("API Routes", test_api_routes),
    ]

    results = {}
    for name, check in checks:
        try:
            check()
            results[name] = True
            print(f"✅ PASS: {name}")
        except Exception as exc:  # noqa: BLE001 - diagnostic reporting
            results[name] = False
            print(f"❌ FAIL: {name} -> {exc}")

    all_passed = all(results.values())
    print("\n" + ("✅ ALL CHECKS PASSED" if all_passed else "⚠️  SOME CHECKS FAILED"))
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
