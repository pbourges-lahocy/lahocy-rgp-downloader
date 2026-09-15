import datetime as dt

from app.rgp.availability import (
    AvailabilityStatus,
    check_availability,
    check_availability_for_utc_period,
)
from app.rgp.provider_ign import IgnProviderIGN
from app.utils.http_client import HeadResult

BASE_URL = "https://rgpdata.ign.fr/pub"


class FakeHeadClient:
    """Simule les réponses HEAD du serveur IGN à partir d'un ensemble d'URLs "existantes"."""

    def __init__(self, existing_urls: set[str], sizes: dict[str, int] | None = None) -> None:
        self._existing = existing_urls
        self._sizes = sizes or {}

    def head(self, url: str) -> HeadResult:
        if url in self._existing:
            return HeadResult(exists=True, size_bytes=self._sizes.get(url, 1000), status_code=200, url=url)
        return HeadResult(exists=False, size_bytes=None, status_code=404, url=url)


def provider() -> IgnProviderIGN:
    return IgnProviderIGN(base_url=BASE_URL, data_dir="data", logsheet_dir="logsheet")


def test_all_hourly_files_present_gives_disponible():
    p = provider()
    start = dt.datetime(2026, 9, 14, 8, 0)
    end = dt.datetime(2026, 9, 14, 9, 0)
    candidate = p.rinex2_candidate("aaer", dt.date(2026, 9, 14), "i", 30)
    client = FakeHeadClient({candidate.url})

    result = check_availability(client, p, "aaer", dt.date(2026, 9, 14), start, end, full_day=False, cadence=30)

    assert result.status == AvailabilityStatus.DISPONIBLE
    assert result.files == [candidate]
    assert not result.used_daily_fallback


def test_missing_hourly_falls_back_to_daily():
    p = provider()
    start = dt.datetime(2026, 9, 14, 8, 0)
    end = dt.datetime(2026, 9, 14, 9, 0)
    daily = p.daily_candidate("aaer", dt.date(2026, 9, 14), 30)
    client = FakeHeadClient({daily.url})  # le fichier horaire n'existe PAS, le journalier oui

    result = check_availability(client, p, "aaer", dt.date(2026, 9, 14), start, end, full_day=False, cadence=30)

    assert result.status == AvailabilityStatus.DISPONIBLE
    assert result.used_daily_fallback
    assert result.files == [daily]
    assert result.warnings  # doit signaler l'usage du fichier journalier


def test_partial_availability_when_some_hours_missing():
    p = provider()
    start = dt.datetime(2026, 9, 14, 8, 0)
    end = dt.datetime(2026, 9, 14, 10, 0)  # heures i, j
    hour_i = p.rinex2_candidate("aaer", dt.date(2026, 9, 14), "i", 30)
    # hour_j absent, daily absent aussi -> statut partiel
    client = FakeHeadClient({hour_i.url})

    result = check_availability(client, p, "aaer", dt.date(2026, 9, 14), start, end, full_day=False, cadence=30)

    assert result.status == AvailabilityStatus.PARTIEL
    assert result.files == [hour_i]
    assert result.missing_sessions == ["j"]


def test_nothing_available_gives_indisponible():
    p = provider()
    start = dt.datetime(2026, 9, 14, 8, 0)
    end = dt.datetime(2026, 9, 14, 9, 0)
    client = FakeHeadClient(set())

    result = check_availability(client, p, "aaer", dt.date(2026, 9, 14), start, end, full_day=False, cadence=30)

    assert result.status == AvailabilityStatus.INDISPONIBLE


def test_full_day_uses_daily_candidate_directly():
    p = provider()
    daily = p.daily_candidate("aaer", dt.date(2026, 9, 14), 30)
    client = FakeHeadClient({daily.url})

    result = check_availability(
        client, p, "aaer", dt.date(2026, 9, 14),
        dt.datetime(2026, 9, 14, 0, 0), dt.datetime(2026, 9, 14, 23, 59),
        full_day=True, cadence=30,
    )

    assert result.status == AvailabilityStatus.DISPONIBLE
    assert result.files == [daily]


def test_suggests_alternative_cadence_when_requested_one_is_missing():
    p = provider()
    start = dt.datetime(2026, 9, 14, 8, 0)
    end = dt.datetime(2026, 9, 14, 9, 0)
    hour_i_1s = p.rinex2_candidate("aaer", dt.date(2026, 9, 14), "i", 1)
    client = FakeHeadClient({hour_i_1s.url})  # 30s absent, 1s présent

    result = check_availability(
        client, p, "aaer", dt.date(2026, 9, 14), start, end,
        full_day=False, cadence=30, other_cadences=(1, 30),
    )

    assert result.status == AvailabilityStatus.INDISPONIBLE
    assert result.available_alternative_cadence == 1
    assert any("1s" in w for w in result.warnings)


def test_utc_period_single_day_delegates_directly():
    p = provider()
    start = dt.datetime(2026, 9, 14, 8, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 9, 14, 9, 0, tzinfo=dt.timezone.utc)
    candidate = p.rinex2_candidate("aaer", dt.date(2026, 9, 14), "i", 30)
    client = FakeHeadClient({candidate.url})

    result = check_availability_for_utc_period(client, p, "aaer", start, end, full_day=False, cadence=30)

    assert result.status == AvailabilityStatus.DISPONIBLE
    assert result.files == [candidate]
    assert not any("chevauche" in w for w in result.warnings)


def test_utc_period_crossing_midnight_merges_two_days():
    p = provider()
    # Chantier de 22h à 1h locales en UTC : ici on simule directement en UTC un
    # chevauchement de minuit (23h -> 1h) pour tester le découpage par jour.
    start = dt.datetime(2026, 9, 14, 23, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 9, 15, 1, 0, tzinfo=dt.timezone.utc)
    day1_hour = p.rinex2_candidate("aaer", dt.date(2026, 9, 14), "x", 30)  # 23h-24h
    day2_hour = p.rinex2_candidate("aaer", dt.date(2026, 9, 15), "a", 30)  # 0h-1h
    client = FakeHeadClient({day1_hour.url, day2_hour.url})

    result = check_availability_for_utc_period(client, p, "aaer", start, end, full_day=False, cadence=30)

    assert result.status == AvailabilityStatus.DISPONIBLE
    assert set(result.files) == {day1_hour, day2_hour}
    assert any("chevauche deux journées UTC" in w for w in result.warnings)


def test_utc_period_full_day_spanning_two_utc_dates_uses_daily_files():
    p = provider()
    start = dt.datetime(2026, 9, 13, 22, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 9, 14, 22, 0, tzinfo=dt.timezone.utc)
    daily_13 = p.daily_candidate("aaer", dt.date(2026, 9, 13), 30)
    daily_14 = p.daily_candidate("aaer", dt.date(2026, 9, 14), 30)
    client = FakeHeadClient({daily_13.url, daily_14.url})

    result = check_availability_for_utc_period(client, p, "aaer", start, end, full_day=True, cadence=30)

    assert result.status == AvailabilityStatus.DISPONIBLE
    assert set(result.files) == {daily_13, daily_14}
