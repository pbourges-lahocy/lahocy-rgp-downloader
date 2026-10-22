import datetime as dt
import json

import httpx
import pytest

from app.config.loader import NtripCasterConfig, load_config
from app.refstations.geocoding import GeocodingError, geocode, parse_geocode_response
from app.refstations.models import STATUS_OFFLINE, STATUS_ONLINE, STATUS_UNKNOWN, ReferenceStation
from app.refstations.nearest import nearest_reference_stations
from app.refstations.ntrip import NtripError, load_ntrip_stations, parse_sourcetable
from app.refstations.rgp_activity import (
    ActivityResult,
    apply_rgp_activity,
    check_rgp_activity,
    latest_published_hour,
    load_rgp_activity,
)
from app.refstations.sources import RGP_SOURCE_ID, available_sources, rgp_reference_stations
from app.rgp.provider_ign import IgnProviderIGN
from app.rgp.stations import Station
from app.utils.http_client import HeadResult, IgnServerUnavailableError

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


def load(client, cache_dir, now, **kwargs):
    kwargs.setdefault("ttl_minutes", 15)
    kwargs.setdefault("retention_days", 90)
    return load_ntrip_stations(client, CASTER, cache_dir, now=now, **kwargs)


NOW = 1_800_000_000.0


def test_parse_marks_native_online_and_federated_unknown():
    stations, _ = parse_sourcetable(SOURCETABLE, "centipede", ("NEAR",))
    by_code = {s.code: s for s in stations}
    assert by_code["1CEN"].status == STATUS_ONLINE
    assert by_code["ABCD"].status == STATUS_UNKNOWN  # réseau fédéré RENAG
    assert "fédérée" in by_code["ABCD"].status_detail


def test_load_ntrip_stations_fetches_then_uses_fresh_cache(tmp_path):
    client = FakeNtripClient(SOURCETABLE)
    first = load(client, tmp_path, NOW)
    second = load(client, tmp_path, NOW + 600)  # 10 min < 15 min

    assert client.headers["Ntrip-Version"] == "Ntrip/2.0"
    assert [s.code for s in first.stations] == ["1CEN", "35JF", "ABCD"]  # NEAR exclu (mount virtuel)
    assert first.warnings and not first.from_cache
    assert second.from_cache and client.calls == 1
    assert second.stations[0].status == STATUS_ONLINE  # l'état est conservé dans le cache


def test_load_ntrip_stations_refetches_once_cache_is_older_than_ttl(tmp_path):
    client = FakeNtripClient(SOURCETABLE)
    load(client, tmp_path, NOW)
    load(client, tmp_path, NOW + 16 * 60)
    assert client.calls == 2


def test_load_ntrip_stations_force_refresh_ignores_fresh_cache(tmp_path):
    client = FakeNtripClient(SOURCETABLE)
    load(client, tmp_path, NOW)
    load(client, tmp_path, NOW, force_refresh=True)
    assert client.calls == 2


def _without(table: str, mount: str) -> str:
    return "\n".join(line for line in table.splitlines() if not line.startswith(f"STR;{mount};"))


def test_native_station_that_disappears_becomes_offline_with_last_seen(tmp_path):
    load(FakeNtripClient(SOURCETABLE), tmp_path, NOW)
    later = NOW + 2 * 86400
    result = load(FakeNtripClient(_without(SOURCETABLE, "1CEN")), tmp_path, later)

    offline = {s.code: s for s in result.stations}["1CEN"]
    assert offline.status == STATUS_OFFLINE
    assert "Hors ligne" in offline.status_detail and "dernière vue" in offline.status_detail
    assert {s.code: s for s in result.stations}["35JF"].status == STATUS_ONLINE


def test_offline_station_is_forgotten_after_retention_period(tmp_path):
    load(FakeNtripClient(SOURCETABLE), tmp_path, NOW)
    table_without = _without(SOURCETABLE, "1CEN")
    load(FakeNtripClient(table_without), tmp_path, NOW + 86400)  # devient hors ligne (vue à NOW)
    result = load(FakeNtripClient(table_without), tmp_path, NOW + 91 * 86400)
    assert "1CEN" not in [s.code for s in result.stations]


def test_offline_station_comes_back_online_when_listed_again(tmp_path):
    load(FakeNtripClient(SOURCETABLE), tmp_path, NOW)
    load(FakeNtripClient(_without(SOURCETABLE, "1CEN")), tmp_path, NOW + 3600)
    result = load(FakeNtripClient(SOURCETABLE), tmp_path, NOW + 7200)
    assert {s.code: s for s in result.stations}["1CEN"].status == STATUS_ONLINE


def test_federated_station_that_disappears_is_not_reported_offline(tmp_path):
    # Pour une base fédérée la table ne dit rien de la connexion : absente = on ne prétend rien.
    load(FakeNtripClient(SOURCETABLE), tmp_path, NOW)
    result = load(FakeNtripClient(_without(SOURCETABLE, "ABCD")), tmp_path, NOW + 3600)
    assert "ABCD" not in [s.code for s in result.stations]


def test_caster_down_falls_back_to_cache_with_every_status_unknown(tmp_path):
    load(FakeNtripClient(SOURCETABLE), tmp_path, NOW)
    down = FakeNtripClient(error=IgnServerUnavailableError("502"))
    result = load(down, tmp_path, NOW + 5 * 86400)

    assert result.stale and len(result.stations) == 3
    assert {s.status for s in result.stations} == {STATUS_UNKNOWN}
    assert "injoignable" in result.warnings[0] and "inconnus" in result.warnings[0]


def test_load_ntrip_stations_raises_when_caster_down_and_no_cache(tmp_path):
    with pytest.raises(IgnServerUnavailableError):
        load(FakeNtripClient(error=IgnServerUnavailableError("502")), tmp_path, NOW)


def test_load_ntrip_stations_rejects_empty_table(tmp_path):
    with pytest.raises(NtripError):
        load(FakeNtripClient("ENDSOURCETABLE"), tmp_path, NOW)


def test_http_error_falls_back_like_unreachable(tmp_path):
    load(FakeNtripClient(SOURCETABLE), tmp_path, NOW)
    response = httpx.Response(500, request=httpx.Request("GET", "https://crtk.net/"))
    err = httpx.HTTPStatusError("boom", request=response.request, response=response)
    assert load(FakeNtripClient(error=err), tmp_path, NOW + 3600).stale


def test_unreadable_or_legacy_cache_is_ignored_not_fatal(tmp_path):
    (tmp_path / "ntrip_centipede_sourcetable.json").write_text('[{"code": "ancien format"}]', encoding="utf-8")
    result = load(FakeNtripClient(SOURCETABLE), tmp_path, NOW)
    assert len(result.stations) == 3 and not result.from_cache


# --- Activité RGP ---


class FakeHeadClient:
    def __init__(self, existing=(), unreachable=()):
        self.existing, self.unreachable, self.urls = set(existing), set(unreachable), []

    def head(self, url):
        self.urls.append(url)
        if any(u in url for u in self.unreachable):
            raise IgnServerUnavailableError("boom")
        return HeadResult(exists=any(e in url for e in self.existing), size_bytes=1, status_code=200, url=url)


PROVIDER = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
UTC = dt.timezone.utc


def test_latest_published_hour_leaves_a_90_minute_publication_margin():
    assert latest_published_hour(dt.datetime(2026, 10, 22, 10, 20, tzinfo=UTC)) == dt.datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
    assert latest_published_hour(dt.datetime(2026, 10, 22, 10, 40, tzinfo=UTC)) == dt.datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
    assert latest_published_hour(dt.datetime(2026, 10, 22, 0, 30, tzinfo=UTC)) == dt.datetime(2026, 10, 21, 23, 0, tzinfo=UTC)


def test_check_rgp_activity_uses_the_right_file_and_falls_back_on_cadence():
    hour = dt.datetime(2026, 10, 22, 7, 0, tzinfo=UTC)  # lettre h, jour 295
    client = FakeHeadClient(existing={"/data_30/aaer295h.26d.Z", "/data_1/renn295h.26d.Z"})

    result = check_rgp_activity(client, PROVIDER, ["AAER", "RENN", "agen"], hour)

    assert result == {"aaer": True, "renn": True, "agen": False}  # renn : seulement en 1 s
    assert any("/data/2026/295/data_30/aaer295h.26d.Z" in u for u in client.urls)


def test_check_rgp_activity_leaves_unreachable_stations_unknown_not_inactive():
    hour = dt.datetime(2026, 10, 22, 7, 0, tzinfo=UTC)
    client = FakeHeadClient(unreachable={"aaer295h"})
    assert "aaer" not in check_rgp_activity(client, PROVIDER, ["aaer", "renn"], hour)


def test_apply_rgp_activity_sets_status_and_detail():
    hour = dt.datetime(2026, 10, 22, 7, 0, tzinfo=UTC)
    stations = [_ref("AAER", 1, 1, "rgp"), _ref("AGEN", 1, 1, "rgp"), _ref("RENN", 1, 1, "rgp")]
    out = apply_rgp_activity(stations, ActivityResult(hour, {"aaer": True, "agen": False}, 0.0))

    assert [s.status for s in out] == [STATUS_ONLINE, STATUS_OFFLINE, STATUS_UNKNOWN]
    assert "07h–08h UTC" in out[0].status_detail
    assert "non diffusée publiquement" in out[1].status_detail


def test_load_rgp_activity_caches_for_the_same_hour_only(tmp_path):
    now = dt.datetime(2026, 10, 22, 10, 20, tzinfo=UTC)
    client = FakeHeadClient(existing={"aaer"})
    first = load_rgp_activity(client, PROVIDER, ["aaer"], tmp_path, 30, (30,), now_utc=now)
    calls = len(client.urls)
    again = load_rgp_activity(client, PROVIDER, ["aaer"], tmp_path, 30, (30,), now_utc=now + dt.timedelta(minutes=5))
    assert again.active == first.active and len(client.urls) == calls  # cache réutilisé

    next_hour = now + dt.timedelta(minutes=25)  # 10:45 -> nouvelle heure de référence (09h)
    load_rgp_activity(client, PROVIDER, ["aaer"], tmp_path, 30, (30,), now_utc=next_hour)
    assert len(client.urls) > calls


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
