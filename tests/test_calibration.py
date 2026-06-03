from app.ai.calibration import calibrate


def test_insufficient_history_uses_ai_estimate():
    out = calibrate(72, "low", {"n": 2, "booked": 2, "disputed": 0})
    assert out["booking_probability"] == 72
    assert out["fraud_risk"] == "low"
    assert out["calibration"]["applied"] is False


def test_none_stats_is_safe():
    out = calibrate(60, "medium", None)
    assert out["booking_probability"] == 60
    assert out["calibration"]["applied"] is False


def test_calibration_blends_toward_empirical_rate():
    # n=10, 80% booked, AI said 50 -> (10*80 + 5*50) / 15 = 70
    out = calibrate(50, "low", {"n": 10, "booked": 8, "disputed": 0})
    assert out["calibration"]["applied"] is True
    assert out["calibration"]["historical_book_rate"] == 80
    assert out["booking_probability"] == 70
    assert out["fraud_risk"] == "low"  # low dispute rate, unchanged


def test_high_dispute_rate_bumps_fraud_risk():
    # 30% dispute rate -> bump low -> medium
    out = calibrate(60, "low", {"n": 10, "booked": 2, "disputed": 3})
    assert out["fraud_risk"] == "medium"
    assert out["calibration"]["historical_dispute_rate"] == 30
    # (10*20 + 5*60) / 15 = 33
    assert out["booking_probability"] == 33


def test_calibrated_probability_is_clamped():
    out = calibrate(100, "low", {"n": 20, "booked": 20, "disputed": 0})
    assert 0 <= out["booking_probability"] <= 100
