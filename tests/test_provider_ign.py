import datetime as dt

from app.rgp.provider_ign import NAV_GPS, OBSERVATION, IgnProviderIGN

BASE_URL = "https://rgpdata.ign.fr/pub"


def make_provider() -> IgnProviderIGN:
    return IgnProviderIGN(base_url=BASE_URL, data_dir="data", logsheet_dir="logsheet")


def test_rinex2_candidate_matches_real_observed_url():
    # Fichier réellement observé sur le serveur le 2026-09-15 (docs/RGP_IGN.md §2.1) :
    # https://rgpdata.ign.fr/pub/data/2026/257/data_30/aaer257a.26d.Z
    provider = make_provider()
    candidate = provider.rinex2_candidate(
        station="aaer", date=dt.date(2026, 9, 14), session="a", cadence=30, file_type=OBSERVATION
    )
    assert candidate.url == f"{BASE_URL}/data/2026/257/data_30/aaer257a.26d.Z"
    assert candidate.filename == "aaer257a.26d.Z"
    assert not candidate.is_daily


def test_daily_candidate_uses_session_zero():
    provider = make_provider()
    candidate = provider.daily_candidate("aaer", dt.date(2026, 9, 14), cadence=30)
    assert candidate.url == f"{BASE_URL}/data/2026/257/data_30/aaer2570.26d.Z"
    assert candidate.is_daily


def test_nav_file_type_changes_extension():
    provider = make_provider()
    candidate = provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "a", 30, NAV_GPS)
    assert candidate.filename == "aaer257a.26n.Z"


def test_hourly_candidates_for_range_covers_expected_sessions():
    provider = make_provider()
    start = dt.datetime(2026, 9, 14, 8, 15)
    end = dt.datetime(2026, 9, 14, 10, 30)
    candidates = provider.hourly_candidates_for_range("aaer", start, end, cadence=30)
    assert [c.session for c in candidates] == ["i", "j", "k"]
    assert candidates[0].url == f"{BASE_URL}/data/2026/257/data_30/aaer257i.26d.Z"


def test_logsheet_urls():
    provider = make_provider()
    assert provider.logsheet_index_url() == f"{BASE_URL}/logsheet/"
    assert provider.logsheet_url("aaer00fra_20251208.log") == f"{BASE_URL}/logsheet/aaer00fra_20251208.log"
