import pytest

from app.geo.distance import distance_km


def test_distance_zero_for_identical_points():
    assert distance_km(48.8566, 2.3522, 48.8566, 2.3522) == pytest.approx(0.0, abs=1e-6)


def test_distance_paris_lyon_known_value():
    # Distance orthodromique Paris-Lyon connue : environ 392 km.
    paris = (48.8566, 2.3522)
    lyon = (45.7640, 4.8357)
    assert distance_km(*paris, *lyon) == pytest.approx(392, rel=0.02)
