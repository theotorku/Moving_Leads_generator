"""
Quick test script to verify the setup is working.
Run this to check if everything is configured correctly.
"""

import sys
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))


def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")
    try:
        import fastapi
        import uvicorn
        import openai
        from supabase import create_client
        import pydantic
        print("✅ All modules imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False


def test_config():
    """Test that configuration loads correctly."""
    print("\nTesting configuration...")
    try:
        from app.config import get_settings
        
        settings = get_settings()
        
        checks = {
            "OpenAI API Key": settings.openai_api_key is not None,
            "Supabase URL": settings.supabase_url is not None,
            "Supabase Key": settings.supabase_key is not None,
            "CORS Origins": len(settings.cors_allow_origins) > 0,
        }
        
        for check, passed in checks.items():
            status = "✅" if passed else "⚠️"
            print(f"  {status} {check}: {passed}")
        
        return all(checks.values())
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False


def test_models():
    """Test that Pydantic models work correctly."""
    print("\nTesting models...")
    try:
        from app.models import RawLead, ScoredLead
        from datetime import date
        
        # Create a test lead
        lead = RawLead(
            full_name="Test User",
            email="test@example.com",
            phone="+1 555-0100",
            move_date=date(2026, 6, 15),
            origin_zip="10001",
            destination_zip="90210",
            home_size="2_bedroom",
            budget=5000,
            urgency="this_month"
        )
        
        print(f"✅ Created test lead: {lead.full_name}")
        
        # Create a scored lead
        scored = ScoredLead(
            **lead.model_dump(),
            score=85,
            reasoning="Test reasoning"
        )
        
        print(f"✅ Created scored lead with score: {scored.score}")
        return True
    except Exception as e:
        print(f"❌ Model error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database():
    """Test Supabase connection (if configured)."""
    print("\nTesting database connection...")
    try:
        from app.db import get_supabase_client
        
        client = get_supabase_client()
        print("✅ Supabase client created successfully")
        
        # Try to query the leads table (will fail if not created yet)
        try:
            response = client.table("leads").select("id").limit(1).execute()
            print(f"✅ Leads table accessible (found {len(response.data)} records)")
        except Exception as e:
            print(f"⚠️  Leads table not accessible yet - migrations may not be applied")
            print(f"   Error: {e}")
        
        return True
    except RuntimeError as e:
        print(f"⚠️  Database not configured: {e}")
        return False
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False


def test_api_routes():
    """Test that API routes are registered."""
    print("\nTesting API routes...")
    try:
        from app.main import app
        
        routes = [route.path for route in app.routes]
        expected_routes = ["/", "/admin", "/portal", "/leads/score"]
        
        for route in expected_routes:
            if route in routes or any(r.startswith(route) for r in routes):
                print(f"✅ Route registered: {route}")
            else:
                print(f"⚠️  Route missing: {route}")
        
        print(f"✅ Total routes: {len(routes)}")
        return True
    except Exception as e:
        print(f"❌ API routes error: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Moving Leads AI - Quick Test")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Configuration", test_config),
        ("Models", test_models),
        ("Database", test_database),
        ("API Routes", test_api_routes),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\n❌ {name} test failed with exception: {e}")
            results[name] = False
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED - System is ready!")
    else:
        print("⚠️  SOME TESTS FAILED - Check errors above")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
