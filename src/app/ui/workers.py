"""Threads Qt pour les opérations réseau (catalogue, recherche, téléchargement).

Toute la logique métier vient des modules `app.rgp.*` déjà testés unitairement
(CLI Phases 2-3) : ces workers ne font qu'orchestrer ces appels hors du thread
d'interface, pour que la fenêtre reste réactive pendant les échanges avec le
serveur IGN.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.config.loader import AppConfig
from app.rgp.availability import (
    AvailabilityResult,
    AvailabilityStatus,
    check_availability_for_utc_period,
)
from app.rgp.catalog import get_catalog
from app.rgp.downloader import download_and_merge_station_files, has_enough_disk_space
from app.rgp.provider_ign import IgnProviderIGN
from app.rgp.report import ChantierInfo, StationReportEntry, build_report
from app.rgp.stations import Station, find_nearest
from app.utils.http_client import IgnServerUnavailableError, RgpHttpClient


def make_client(config: AppConfig) -> RgpHttpClient:
    return RgpHttpClient(
        timeout_seconds=config.network.timeout_seconds,
        retries=config.network.retries,
        retry_backoff_seconds=config.network.retry_backoff_seconds,
        user_agent=config.network.user_agent,
    )


def make_provider(config: AppConfig) -> IgnProviderIGN:
    return IgnProviderIGN(
        base_url=config.ign.base_url, data_dir=config.ign.data_dir, logsheet_dir=config.ign.logsheet_dir
    )


class CatalogWorker(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, config: AppConfig, force_refresh: bool, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._force_refresh = force_refresh

    def run(self) -> None:
        provider = make_provider(self._config)
        try:
            with make_client(self._config) as client:
                stations = get_catalog(
                    client,
                    provider,
                    self._config.cache_dir,
                    self._config.cache.catalog_filename,
                    self._config.cache.catalog_ttl_days,
                    force_refresh=self._force_refresh,
                )
            self.succeeded.emit(stations)
        except IgnServerUnavailableError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Erreur inattendue lors du chargement du catalogue : {exc}")


@dataclass
class StationSearchResult:
    station: Station
    distance_km: float
    availability: AvailabilityResult


class SearchWorker(QThread):
    progress = Signal(int, int)
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        stations: list[Station],
        lat: float,
        lon: float,
        start_utc: dt.datetime,
        end_utc: dt.datetime,
        full_day: bool,
        cadence: int,
        limit: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._stations = stations
        self._lat = lat
        self._lon = lon
        self._start_utc = start_utc
        self._end_utc = end_utc
        self._full_day = full_day
        self._cadence = cadence
        self._limit = limit

    def run(self) -> None:
        provider = make_provider(self._config)
        nearest = find_nearest(self._stations, self._lat, self._lon, limit=self._limit)
        results: list[StationSearchResult] = []
        try:
            with make_client(self._config) as client:
                for i, sd in enumerate(nearest, start=1):
                    availability = check_availability_for_utc_period(
                        client,
                        provider,
                        sd.station.code,
                        self._start_utc,
                        self._end_utc,
                        full_day=self._full_day,
                        cadence=self._cadence,
                        other_cadences=self._config.ign.cadences,
                    )
                    results.append(
                        StationSearchResult(station=sd.station, distance_km=sd.distance_km, availability=availability)
                    )
                    self.progress.emit(i, len(nearest))
            self.succeeded.emit(results)
        except IgnServerUnavailableError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Erreur inattendue lors de la recherche des stations : {exc}")


@dataclass
class DownloadFileEvent:
    station_code: str
    filename: str
    ok: bool
    error: str = ""


class DownloadWorker(QThread):
    progress = Signal(str)
    file_done = Signal(DownloadFileEvent)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        chantier: ChantierInfo,
        destination: Path,
        site_date: dt.date,
        entries: list[StationSearchResult],
        keep_systems: set[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._chantier = chantier
        self._destination = destination
        self._site_date = site_date
        self._entries = entries
        self._keep_systems = keep_systems

    def run(self) -> None:
        downloadable = [
            e for e in self._entries if e.availability.status != AvailabilityStatus.INDISPONIBLE and e.availability.files
        ]
        total_size = sum(e.availability.total_size_bytes for e in downloadable)
        chantier_dir = self._destination / "RGP" / self._site_date.isoformat()

        if downloadable and not has_enough_disk_space(self._destination, total_size):
            self.failed.emit(
                f"Espace disque insuffisant sur {self._destination} "
                f"(besoin estimé : {total_size / (1024 * 1024):.1f} Mo). Téléchargement annulé."
            )
            return

        report_entries: list[StationReportEntry] = []
        try:
            with make_client(self._config) as client:
                for entry in self._entries:
                    report_entry = StationReportEntry(
                        station=entry.station, distance_km=entry.distance_km, availability=entry.availability
                    )
                    report_entries.append(report_entry)
                    if entry not in downloadable:
                        continue

                    station_dir = chantier_dir / entry.station.code.upper()
                    self.progress.emit(f"Téléchargement {entry.station.code.upper()}...")
                    result = download_and_merge_station_files(
                        client, entry.availability.files, station_dir, self._site_date, self._keep_systems
                    )
                    report_entry.downloaded_files = result.downloaded_files
                    report_entry.merged_path = result.merged_path
                    report_entry.merge_error = result.merge_error
                    report_entry.constellations_kept = self._keep_systems

                    for f in result.downloaded_files:
                        if not f.ok:
                            self.file_done.emit(
                                DownloadFileEvent(
                                    station_code=entry.station.code.upper(),
                                    filename=f.candidate.filename,
                                    ok=False,
                                    error=f.error or "",
                                )
                            )
                    if result.merged_path:
                        self.file_done.emit(
                            DownloadFileEvent(
                                station_code=entry.station.code.upper(), filename=result.merged_path.name, ok=True
                            )
                        )
                    elif result.merge_error:
                        self.file_done.emit(
                            DownloadFileEvent(
                                station_code=entry.station.code.upper(),
                                filename="(fusion)",
                                ok=False,
                                error=result.merge_error,
                            )
                        )

            report_text = build_report(self._chantier, report_entries, generated_at=dt.datetime.now())
            chantier_dir.mkdir(parents=True, exist_ok=True)
            report_path = chantier_dir / "rapport_RGP.txt"
            report_path.write_text(report_text, encoding="utf-8")
            self.succeeded.emit(str(report_path))
        except IgnServerUnavailableError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Erreur inattendue lors du téléchargement : {exc}")
