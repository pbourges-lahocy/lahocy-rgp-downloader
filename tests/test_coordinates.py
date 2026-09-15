import pytest

from app.geo.coordinates import (
    InvalidCoordinatesError,
    lambert93_to_wgs84,
    parse_igs_sexagesimal,
    wgs84_to_lambert93,
)

# Tour Eiffel : référence connue, coordonnées IGN publiques.
TOUR_EIFFEL_L93 = (648237.66, 6862271.99)
TOUR_EIFFEL_WGS84 = (48.858260, 2.294500)


def test_lambert93_to_wgs84_round_trip():
    lat, lon = lambert93_to_wgs84(*TOUR_EIFFEL_L93)
    assert lat == pytest.approx(TOUR_EIFFEL_WGS84[0], abs=1e-3)
    assert lon == pytest.approx(TOUR_EIFFEL_WGS84[1], abs=1e-3)


def test_wgs84_to_lambert93_round_trip():
    x, y = wgs84_to_lambert93(*TOUR_EIFFEL_WGS84)
    assert x == pytest.approx(TOUR_EIFFEL_L93[0], abs=50)
    assert y == pytest.approx(TOUR_EIFFEL_L93[1], abs=50)


def test_round_trip_consistency():
    lat, lon = lambert93_to_wgs84(*TOUR_EIFFEL_L93)
    x, y = wgs84_to_lambert93(lat, lon)
    assert x == pytest.approx(TOUR_EIFFEL_L93[0], abs=1e-2)
    assert y == pytest.approx(TOUR_EIFFEL_L93[1], abs=1e-2)


def test_lambert93_rejects_out_of_range_coordinates():
    with pytest.raises(InvalidCoordinatesError):
        lambert93_to_wgs84(x=99, y=99)


def test_wgs84_rejects_invalid_latitude():
    with pytest.raises(InvalidCoordinatesError):
        wgs84_to_lambert93(lat=120, lon=2)


def test_parse_igs_sexagesimal_latitude():
    # Exemple réel observé sur la fiche de site AAER00FRA (docs/RGP_IGN.md §2.3).
    assert parse_igs_sexagesimal("+494656.88") == pytest.approx(49.782466, abs=1e-5)


def test_parse_igs_sexagesimal_longitude():
    assert parse_igs_sexagesimal("+0043833.53") == pytest.approx(4.642647, abs=1e-5)


def test_parse_igs_sexagesimal_negative():
    assert parse_igs_sexagesimal("-0012000.00") == pytest.approx(-1.333333, abs=1e-5)


def test_parse_igs_sexagesimal_tolerates_missing_sign():
    # Observé en pratique sur certaines fiches RGP réelles (ex. bapi00fra, cabn00fra) :
    # le signe '+' est parfois omis pour une valeur positive.
    assert parse_igs_sexagesimal("483259.80") == pytest.approx(48.549944, abs=1e-5)


def test_parse_igs_sexagesimal_tolerates_trailing_dot_without_digits():
    # Observé sur la fiche réelle fers00fra : "+461336." sans décimales de secondes.
    assert parse_igs_sexagesimal("+461336.") == pytest.approx(46.226667, abs=1e-5)


def test_parse_igs_sexagesimal_rejects_too_short_value():
    with pytest.raises(ValueError):
        parse_igs_sexagesimal("123.45")
