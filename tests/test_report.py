import datetime as dt
from pathlib import Path

from app.rgp.availability import AvailabilityResult, AvailabilityStatus
from app.rgp.downloader import DownloadedFile
from app.rgp.provider_ign import IgnProviderIGN
from app.rgp.report import ChantierInfo, StationReportEntry, build_report
from app.rgp.stations import Station


def make_station(code: str) -> Station:
    return Station(
        code=code,
        site_id9=f"{code.upper()}00FRA",
        name=code.upper(),
        city="Ville",
        country="FRA",
        latitude=48.0,
        longitude=2.0,
        elevation_m=100.0,
        satellite_system="GPS+GLO",
        logsheet_filename=f"{code}00fra_20250101.log",
    )


def make_chantier() -> ChantierInfo:
    return ChantierInfo(
        x_l93=345678.123,
        y_l93=6789123.456,
        lat=48.123456,
        lon=-1.654321,
        site_date=dt.date(2026, 9, 15),
        period_label="08:15 -> 17:45",
    )


def test_report_contains_chantier_and_station_sections():
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    candidate = provider.rinex2_candidate("ren1", dt.date(2026, 9, 15), "i", 30)
    availability = AvailabilityResult(
        station_code="ren1", requested_cadence=30, status=AvailabilityStatus.DISPONIBLE, files=[candidate]
    )
    downloaded = DownloadedFile(candidate=candidate, raw_path=Path("REN1/ren1258i.26d.Z"), processed_path=Path("REN1/ren1258i.26o"))
    entry = StationReportEntry(station=make_station("ren1"), distance_km=17.8, availability=availability, downloaded_files=[downloaded])

    report = build_report(make_chantier(), [entry], generated_at=dt.datetime(2026, 9, 15, 18, 0, 0))

    assert "X L93 : 345678.123" in report
    assert "Y L93 : 6789123.456" in report
    assert "48.123456" in report
    assert "15/09/2026" in report
    assert "REN1" in report
    assert "17.8 km" in report
    assert "disponibles" in report
    assert "ren1258i.26o" in report
    assert "RGP IGN" in report
    assert "15/09/2026 18:00:00" in report


def test_report_lists_warnings_and_download_errors():
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    candidate = provider.rinex2_candidate("stbr", dt.date(2026, 9, 15), "i", 30)
    availability = AvailabilityResult(
        station_code="stbr",
        requested_cadence=30,
        status=AvailabilityStatus.PARTIEL,
        files=[candidate],
        missing_sessions=["j"],
        warnings=["Données partielles pour STBR : heures manquantes j."],
    )
    failed_download = DownloadedFile(candidate=candidate, error="Téléchargement impossible : timeout")
    entry = StationReportEntry(station=make_station("stbr"), distance_km=48.2, availability=availability, downloaded_files=[failed_download])

    report = build_report(make_chantier(), [entry], generated_at=dt.datetime(2026, 9, 15, 18, 0, 0))

    assert "Avertissements :" in report
    assert "heures manquantes j" in report
    assert "Téléchargement impossible" in report


def test_report_handles_unavailable_station_without_files():
    availability = AvailabilityResult(station_code="chld", requested_cadence=30, status=AvailabilityStatus.INDISPONIBLE)
    entry = StationReportEntry(station=make_station("chld"), distance_km=60.0, availability=availability)

    report = build_report(make_chantier(), [entry], generated_at=dt.datetime(2026, 9, 15, 18, 0, 0))

    assert "indisponibles" in report
    assert "Fichiers : aucun" in report


def test_report_shows_merged_file_and_constellations():
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    candidate = provider.rinex2_candidate("ren1", dt.date(2026, 9, 15), "i", 30)
    availability = AvailabilityResult(
        station_code="ren1", requested_cadence=30, status=AvailabilityStatus.DISPONIBLE, files=[candidate]
    )
    entry = StationReportEntry(
        station=make_station("ren1"),
        distance_km=17.8,
        availability=availability,
        merged_path=Path("REN1/ren1258_0800-1700_G.26o"),
        constellations_kept={"G"},
    )

    report = build_report(make_chantier(), [entry], generated_at=dt.datetime(2026, 9, 15, 18, 0, 0))

    assert "Fichiers : ren1258_0800-1700_G.26o" in report
    assert "Constellations conservées : G" in report


def test_report_surfaces_merge_error_as_warning():
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    candidate = provider.rinex2_candidate("ren1", dt.date(2026, 9, 15), "i", 30)
    availability = AvailabilityResult(
        station_code="ren1", requested_cadence=30, status=AvailabilityStatus.DISPONIBLE, files=[candidate]
    )
    downloaded = DownloadedFile(candidate=candidate, raw_path=Path("REN1/ren1258i.26d.Z"), processed_path=Path("REN1/ren1258i.26o"))
    entry = StationReportEntry(
        station=make_station("ren1"),
        distance_km=17.8,
        availability=availability,
        downloaded_files=[downloaded],
        merge_error="types d'observation différents",
    )

    report = build_report(make_chantier(), [entry], generated_at=dt.datetime(2026, 9, 15, 18, 0, 0))

    assert "fusion des fichiers échouée" in report
    assert "ren1258i.26o" in report  # repli sur le fichier individuel
