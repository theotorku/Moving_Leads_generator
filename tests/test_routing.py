from app.services.admin_service import _profile_fit

LEAD = {
    "route_type": "interstate",
    "home_size": "2_bedroom",
    "estimated_job_value": 6000,
    "origin_zip": "10001",
    "destination_zip": "90210",
}


def test_empty_profile_matches_everything():
    assert _profile_fit(LEAD, {})["match"] is True
    assert _profile_fit(LEAD, None)["match"] is True


def test_route_type_mismatch():
    fit = _profile_fit(LEAD, {"accepted_route_types": ["local"]})
    assert fit["match"] is False
    assert any("interstate" in r for r in fit["reasons"])


def test_zip_prefix_match_and_miss():
    assert _profile_fit(LEAD, {"service_zips": ["100"]})["match"] is True   # origin 10001
    assert _profile_fit(LEAD, {"service_zips": ["902"]})["match"] is True   # destination 90210
    miss = _profile_fit(LEAD, {"service_zips": ["303"]})
    assert miss["match"] is False
    assert "outside service area" in miss["reasons"]


def test_min_job_value():
    assert _profile_fit(LEAD, {"min_job_value": 8000})["match"] is False
    assert _profile_fit(LEAD, {"min_job_value": 5000})["match"] is True


def test_home_size():
    assert _profile_fit(LEAD, {"accepted_home_sizes": ["studio", "1_bedroom"]})["match"] is False
    assert _profile_fit(LEAD, {"accepted_home_sizes": ["2_bedroom"]})["match"] is True


def test_multiple_mismatch_reasons_accumulate():
    fit = _profile_fit(LEAD, {"accepted_route_types": ["local"], "min_job_value": 9000})
    assert fit["match"] is False
    assert len(fit["reasons"]) == 2
