from pathlib import Path

import pytest

from app.rgp.catalog import (
    build_catalog_from_network,
    list_logsheet_filenames,
    load_cached_catalog,
    parse_logsheet,
    save_catalog_to_cache,
)
from app.rgp.provider_ign import IgnProviderIGN

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FakeHttpClient:
    """Simule RgpHttpClient en lisant des fixtures locales — aucun accès réseau."""

    def __init__(self, index_html: str, logsheet_dir: Path) -> None:
        self._index_html = index_html
        self._logsheet_dir = logsheet_dir

    def get_text(self, url: str) -> str:
        if url.endswith("/logsheet/"):
            return self._index_html
        filename = url.rsplit("/", 1)[-1]
        path = self._logsheet_dir / filename
        if not path.exists():
            raise FileNotFoundError(url)
        return path.read_text(encoding="utf-8")


@pytest.fixture
def provider() -> IgnProviderIGN:
    return IgnProviderIGN(
        base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet"
    )


@pytest.fixture
def fake_client() -> FakeHttpClient:
    index_html = (FIXTURES_DIR / "logsheet_index.html").read_text(encoding="utf-8")
    return FakeHttpClient(index_html, FIXTURES_DIR / "logsheet")


def test_parse_logsheet_extracts_expected_fields():
    text = (FIXTURES_DIR / "logsheet" / "aaer00fra_20251208.log").read_text(encoding="utf-8")
    station = parse_logsheet(text, "aaer00fra_20251208.log")

    assert station.code == "aaer"
    assert station.site_id9 == "AAER00FRA"
    assert station.name == "Aérodrome des Ardennes Etienne Riché"
    assert station.city == "CHARLEVILLE-MEZIERES"
    assert station.country == "FRA"
    assert station.latitude == pytest.approx(49.782466, abs=1e-5)
    assert station.longitude == pytest.approx(4.642647, abs=1e-5)
    assert station.elevation_m == pytest.approx(199.3)
    # Doit prendre la dernière config réceptrice réelle (3.2), pas le gabarit (3.x).
    assert station.satellite_system == "GPS+GLO+GAL+BDS+SBAS"


def test_parse_logsheet_rejects_incomplete_fiche():
    text = (FIXTURES_DIR / "logsheet" / "broken00fra_20200101.log").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        parse_logsheet(text, "broken00fra_20200101.log")


def test_list_logsheet_filenames(provider, fake_client):
    filenames = list_logsheet_filenames(fake_client, provider)
    assert filenames == ["aaer00fra_20251208.log", "broken00fra_20200101.log"]


def test_build_catalog_from_network_continues_after_broken_fiche(provider, fake_client):
    stations, errors = build_catalog_from_network(fake_client, provider)
    assert len(stations) == 1
    assert stations[0].code == "aaer"
    assert len(errors) == 1
    assert "broken00fra_20200101.log" in errors[0]


def test_catalog_cache_round_trip(provider, fake_client, tmp_path):
    stations, _errors = build_catalog_from_network(fake_client, provider)
    save_catalog_to_cache(tmp_path, "stations.json", stations)

    cached = load_cached_catalog(tmp_path, "stations.json", ttl_days=30)
    assert cached is not None
    assert len(cached) == 1
    assert cached[0].code == "aaer"


def test_catalog_cache_expired_returns_none(provider, fake_client, tmp_path):
    stations, _errors = build_catalog_from_network(fake_client, provider)
    save_catalog_to_cache(tmp_path, "stations.json", stations)

    cached = load_cached_catalog(tmp_path, "stations.json", ttl_days=0)
    assert cached is None
