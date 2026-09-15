"""Génération du rapport de téléchargement (rapport_RGP.txt, cahier des charges §10)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from app.rgp.availability import AvailabilityResult, AvailabilityStatus
from app.rgp.downloader import DownloadedFile
from app.rgp.stations import Station

_STATUS_LABELS = {
    AvailabilityStatus.DISPONIBLE: "disponibles",
    AvailabilityStatus.PARTIEL: "partielles",
    AvailabilityStatus.INDISPONIBLE: "indisponibles",
}


@dataclass
class StationReportEntry:
    station: Station
    distance_km: float
    availability: AvailabilityResult
    downloaded_files: list[DownloadedFile] = field(default_factory=list)
    merged_path: Path | None = None
    merge_error: str | None = None
    constellations_kept: set[str] | None = None


@dataclass
class ChantierInfo:
    x_l93: float
    y_l93: float
    lat: float
    lon: float
    site_date: dt.date
    period_label: str


def build_report(chantier: ChantierInfo, entries: list[StationReportEntry], generated_at: dt.datetime) -> str:
    lines: list[str] = []
    lines.append("LAHOCY — Téléchargement RGP")
    lines.append("")
    lines.append("Chantier :")
    lines.append(f"X L93 : {chantier.x_l93:.3f}")
    lines.append(f"Y L93 : {chantier.y_l93:.3f}")
    lines.append("")
    lines.append("WGS84 :")
    lines.append(f"{chantier.lat:.6f}")
    lines.append(f"{chantier.lon:.6f}")
    lines.append("")
    lines.append("Date :")
    lines.append(chantier.site_date.strftime("%d/%m/%Y"))
    lines.append("")
    lines.append("Période demandée :")
    lines.append(chantier.period_label)
    lines.append("")
    lines.append("Stations sélectionnées :")

    all_warnings: list[str] = []

    for entry in entries:
        lines.append("")
        lines.append(entry.station.code.upper())
        lines.append(f"Distance : {entry.distance_km:.1f} km")
        lines.append(f"Données : {_STATUS_LABELS[entry.availability.status]}")

        if entry.constellations_kept:
            lines.append(f"Constellations conservées : {', '.join(sorted(entry.constellations_kept))}")

        if entry.merged_path is not None:
            lines.append(f"Fichiers : {entry.merged_path.name}")
        elif entry.downloaded_files:
            ok_files = [f for f in entry.downloaded_files if f.ok]
            if ok_files:
                names = ", ".join(f.processed_path.name if f.processed_path else f.candidate.filename for f in ok_files)
                lines.append(f"Fichiers : {names}")
        elif entry.availability.files:
            names = ", ".join(f.filename for f in entry.availability.files)
            lines.append(f"Fichiers : {names} (non téléchargés)")
        else:
            lines.append("Fichiers : aucun")

        if entry.downloaded_files:
            for f in entry.downloaded_files:
                if not f.ok:
                    all_warnings.append(f"{entry.station.code.upper()} : {f.error}")
        if entry.merge_error:
            all_warnings.append(f"{entry.station.code.upper()} : fusion des fichiers échouée : {entry.merge_error}")

        all_warnings.extend(f"{entry.station.code.upper()} : {w}" for w in entry.availability.warnings)

    if all_warnings:
        lines.append("")
        lines.append("Avertissements :")
        for warning in all_warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("Source :")
    lines.append("RGP IGN (https://rgpdata.ign.fr)")
    lines.append("")
    lines.append("Téléchargement effectué le :")
    lines.append(generated_at.strftime("%d/%m/%Y %H:%M:%S"))

    return "\n".join(lines) + "\n"
