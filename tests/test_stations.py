from app.rgp.stations import Station, find_nearest


def make_station(code: str, lat: float, lon: float) -> Station:
    return Station(
        code=code,
        site_id9=f"{code.upper()}00FRA",
        name=code.upper(),
        city="",
        country="FRA",
        latitude=lat,
        longitude=lon,
        elevation_m=100.0,
        satellite_system="GPS+GLO",
        logsheet_filename=f"{code}00fra_20250101.log",
    )


def test_find_nearest_orders_by_distance():
    site_lat, site_lon = 48.8566, 2.3522  # Paris
    far = make_station("far", 43.2965, 5.3698)  # Marseille
    near = make_station("near", 48.8600, 2.3500)  # tout près de Paris
    mid = make_station("mid", 47.2184, -1.5536)  # Nantes

    ranked = find_nearest([far, mid, near], site_lat, site_lon)

    assert [r.station.code for r in ranked] == ["near", "mid", "far"]
    assert ranked[0].distance_km < ranked[1].distance_km < ranked[2].distance_km


def test_find_nearest_respects_limit():
    site_lat, site_lon = 48.8566, 2.3522
    stations = [make_station(f"s{i}", 48.8566 + i * 0.1, 2.3522) for i in range(5)]

    ranked = find_nearest(stations, site_lat, site_lon, limit=2)

    assert len(ranked) == 2
