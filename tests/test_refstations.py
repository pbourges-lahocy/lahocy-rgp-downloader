import json
import os
import time

import httpx
import pytest

from app.config.loader import NtripCasterConfig, load_config
from app.refstations.geocoding import GeocodingError, geocode, parse_geocode_response
from app.refstations.models import ReferenceStation
from app.refstations.nearest import nearest_reference_stations
from app.refstations.ntrip import NtripError, load_ntrip_stations, parse_sourcetable
from app.refstations.sources import RGP_SOURCE_ID, available_sources, rgp_reference_stations
from app.rgp.stations import Station
from app.utils.http_client import IgnServerUnavailableError

# Lignes réelles de la table https://crtk.net/ (19 champs), plus des cas dégradés.
SOURCETABLE = "\n".join(
    [
        "CAS;crtk.net;2101;Millipede-caster;Centipede-RTK;0;FRA;45.99;-1.02;0.0.0.0;0;https//map.centipede-rtk.org",
        "NET;ASSO;CENTIPEDE-RTK;B;N;https://www.centipede-rtk.org/terms-conditions;https://docs.centipede.fr;contact@centipede-rtk.org;none",
        "STR;1CEN;Charnoz-sur-Ain;RTCM3;1004,1005,1006;2;GLO+GAL+BDS+GPS;NONE;FRA;45.864;5.222;0;0;NTRIP RTKBase U-blox_ZED-F9P 2.7.0 1.51;none;N;N;15200;CentipedeRTK",
        "STR;35JF;FRA;RTCM3;1004,1005,1006;2;GLO+GAL+SBS+BDS+GPS;NONE;FRA;48.651;-2.001;0;0;NTRIP RTKBase Ublox_ZED-F9P 2.3.1;none;N;N;15200;CentipedeRTK",
        "STR;ABCD;Orsay;RTCM 3.2 MSM7;1004;2;GPS+GLO;RENAG;FRA;48.70;2.18;0;0;gen;none;N;N;9600;OSUG",
        "STR;NEAR;NEAR;RTCM3;1004;2;GPS;NONE;FRA;46.000;-1.213;1;0;gen;none;N;N;15200;CentipedeRTK",
        "STR;BADLAT;Casse;RTCM3;1004;2;GPS;NONE;FRA;abc;2.0;0;0;gen;none;N;N;15200;CentipedeRTK",
        "STR;ZERO;Nulle;RTCM3;1004;2;GPS;NONE;FRA;0.0;0.0;0;0;gen;none;N;N;15200;CentipedeRTK",
        "STR;COURT;trop;court",
        "ENDSOURCETABLE",
    ]
)

CASTER = NtripCasterConfig(
    id="centipede", name="Centipède RTK", sourcetable_url="https://crtk.net/", virtual_mounts=("NEAR", "NEAR4")
)


def test_parse_sourcetable_extracts_valid_stations_and_skips_the_rest():
    stations, skipped = parse_sourcetable(SOURCETABLE, "centipede", ("NEAR", "NEAR4"))

    assert [s.code for s in stations] == ["1CEN", "35JF", "ABCD"]
    cen = stations[0]
    assert (cen.latitude, cen.longitude) == (45.864, 5.222)
    assert cen.name == "Charnoz-sur-Ain"
    assert cen.constellations == "GLO+GAL+BDS+GPS"
    assert cen.network == "CentipedeRTK"  # réseau "NONE" -> sous-réseau du champ divers
    assert stations[1].name == ""  # identifiant = code pays : pas un vrai nom
    assert stations[2].network == "RENAG"
    assert len(skipped) == 3  # coordonnées illisibles, nulles, ligne trop courte
    assert not any("NEAR" in s for s in skipped)  # le mount virtuel est écarté sans bruit


def test_parse_sourcetable_without_virtual_filter_keeps_near():
    stations, _ = parse_sourcetable(SOURCETABLE, "centipede")
    assert "NEAR" in [s.code for s in stations]


class FakeNtripClient:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls, self.headers = text, error, 0, None

    def get_text(self, url, headers=None):
        self.calls += 1
        self.headers = headers
        if self.error:
            raise self.error
        return self.text


def test_load_ntrip_stations_fetches_then_uses_fresh_cache(tmp_path):
    client = FakeNtripClient(SOURCETABLE)
    first = load_ntrip_stations(client, CASTER, tmp_path, ttl_days=1)
    second = load_ntrip_stations(client, CASTER, tmp_path, ttl_days=1)

    assert client.headers["Ntrip-Version"] == "Ntrip/2.0"
    assert [s.code for s in first.stations] == ["1CEN", "35JF", "ABCD"]  # NEAR exclu (mount virtuel)
    assert first.warnings and not first.from_cache
    assert second.from_cache and client.calls == 1


def test_load_ntrip_stations_force_refresh_ignores_fresh_cache(tmp_path):
    client = FakeNtripClient(SOURCETABLE)
    load_ntrip_stations(client, CASTER, tmp_path, ttl_days=1)
    load_ntrip_stations(client, CASTER, tmp_path, ttl_days=1, force_refresh=True)
    assert client.calls == 2


def test_load_ntrip_stations_falls_back_to_stale_cache_when_caster_is_down(tmp_path):
    load_ntrip_stations(FakeNtripClient(SOURCETABLE), CASTER, tmp_path, ttl_days=1)
    cache = tmp_path / "ntrip_centipede_sourcetable.json"
    old = time.time() - 5 * 86400
    os.utime(cache, (old, old))

    down = FakeNtripClient(error=IgnServerUnavailableError("502"))
    result = load_ntrip_stations(down, CASTER, tmp_path, ttl_days=1)

    assert result.stale and len(result.stations) == 3
    assert "injoignable" in result.warnings[0] and "5 jour" in result.warnings[0]


def test_load_ntrip_stations_raises_when_caster_down_and_no_cache(tmp_path):
    with pytest.raises(IgnServerUnavailableError):
        load_ntrip_stations(FakeNtripClient(error=IgnServerUnavailableError("502")), CASTER, tmp_path, ttl_days=1)


def test_load_ntrip_stations_rejects_empty_table(tmp_path):
    with pytest.raises(NtripError):
        load_ntrip_stations(FakeNtripClient("ENDSOURCETABLE"), CASTER, tmp_path, ttl_days=1)


def test_load_ntrip_stations_http_error_falls_back_like_unreachable(tmp_path):
    load_ntrip_stations(FakeNtripClient(SOURCETABLE), CASTER, tmp_path, ttl_days=1)
    response = httpx.Response(500, request=httpx.Request("GET", "https://crtk.net/"))
    err = httpx.HTTPStatusError("boom", request=response.request, response=response)
    result = load_ntrip_stations(FakeNtripClient(error=err), CASTER, tmp_path, ttl_days=0, force_refresh=True)
    assert result.stale


# --- Géocodage ---

GEOCODE_JSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-1.669676, 48.112112]},
            "properties": {"label": "12 Rue de Paris 35000 Rennes", "score": 0.98},
        },
        {"type": "Feature", "geometry": {"type": "Point"}, "properties": {"label": "cassé"}},
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [2.35, 48.85]},
            "properties": {"name": "Paris", "score": 0.5},
        },
    ],
}


def test_parse_geocode_response_inverts_lon_lat_and_skips_malformed():
    results = parse_geocode_response(GEOCODE_JSON)
    assert [r.label for r in results] == ["12 Rue de Paris 35000 Rennes", "Paris"]
    assert (results[0].latitude, results[0].longitude) == (48.112112, -1.669676)


def test_geocode_builds_encoded_query_and_parses(tmp_path):
    class Client:
        url = None

        def get_text(self, url, headers=None):
            Client.url = url
            return json.dumps(GEOCODE_JSON)

    results = geocode(Client(), "https://data.geopf.fr/geocodage/search", "12 rue de Paris, Rennes", 5)
    assert "q=12+rue+de+Paris%2C+Rennes" in Client.url and "limit=5" in Client.url
    assert len(results) == 2


def test_geocode_rejects_empty_query_and_bad_json():
    class Bad:
        def get_text(self, url, headers=None):
            return "<html>pas du json</html>"

    with pytest.raises(ValueError):
        geocode(Bad(), "https://x", "   ", 5)
    with pytest.raises(GeocodingError):
        geocode(Bad(), "https://x", "rennes", 5)


# --- Plus proches + registre ---


def _ref(code, lat, lon, source="centipede"):
    return ReferenceStation(source_id=source, code=code, name=code, latitude=lat, longitude=lon)


def test_nearest_reference_stations_sorted_and_limited():
    stations = [_ref("far", 43.3, 5.4), _ref("near", 48.86, 2.35), _ref("mid", 47.2, -1.55)]
    ranked = nearest_reference_stations(stations, 48.8566, 2.3522, limit=2)
    assert [r.station.code for r in ranked] == ["near", "mid"]
    assert ranked[0].distance_km < ranked[1].distance_km


def test_reference_station_key_is_unique_across_sources():
    assert _ref("ABCD", 1, 1, "rgp").key != _ref("ABCD", 1, 1, "centipede").key


def test_rgp_stations_conversion_and_available_sources():
    rgp = Station(
        code="aaer", site_id9="AAER00FRA", name="Aérodrome", city="X", country="FRA", latitude=49.78,
        longitude=4.64, elevation_m=199.0, satellite_system="GPS+GLO", logsheet_filename="aaer.log",
    )
    ref = rgp_reference_stations([rgp])[0]
    assert (ref.source_id, ref.code, ref.network) == (RGP_SOURCE_ID, "AAER", "RGP")

    from pathlib import Path

    config = load_config(Path(__file__).resolve().parents[1] / "config" / "config.yaml")
    assert [s.id for s in available_sources(config)] == ["rgp", "centipede"]
    assert config.reference.ntrip_casters[0].sourcetable_url == "https://crtk.net/"
