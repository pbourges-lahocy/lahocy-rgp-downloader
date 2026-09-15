"""Téléchargement réel des fichiers RINEX sélectionnés vers le dossier du chantier.

Produit, pour chaque station, un dossier contenant à la fois les fichiers
téléchargés tels quels et leur version RINEX directement exploitable
(décompressée et, si besoin, convertie depuis Hatanaka), en conservant le
nom RINEX standard plutôt qu'un nom générique (cahier des charges §8).

Quand la période demandée nécessite plusieurs fichiers horaires, ou qu'un
filtrage par constellation est demandé, `download_and_merge_station_files`
les fusionne en un seul fichier RINEX continu via `app.rgp.rinex_merge`.
"""

from __future__ import annotations

import datetime as dt
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.rgp.provider_ign import RinexFileCandidate
from app.rgp.rinex import RinexProcessingError, process_downloaded_file
from app.rgp.rinex_merge import RinexMergeError, merge_rinex2_observation_files
from app.utils.dates import DAILY_SESSION_CODE, day_of_year, session_letter_to_hour
from app.utils.http_client import IgnServerUnavailableError, RgpHttpClient


@dataclass
class DownloadedFile:
    candidate: RinexFileCandidate
    raw_path: Path | None = None
    processed_path: Path | None = None
    size_bytes: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def has_enough_disk_space(destination: Path, required_bytes: int, safety_margin: float = 1.1) -> bool:
    """Vérifie qu'il reste assez d'espace disque avant de lancer les téléchargements.

    `destination` peut ne pas encore exister (dossier créé plus tard) : on vérifie
    alors l'espace disponible sur son premier ancêtre existant.
    """
    probe = destination
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return usage.free >= required_bytes * safety_margin


def download_station_files(
    client: RgpHttpClient,
    candidates: list[RinexFileCandidate],
    station_dir: Path,
    process: bool = True,
) -> list[DownloadedFile]:
    """Télécharge chaque candidat vers station_dir, puis le rend exploitable si `process`."""
    station_dir.mkdir(parents=True, exist_ok=True)
    results: list[DownloadedFile] = []

    for candidate in candidates:
        result = DownloadedFile(candidate=candidate)
        raw_path = station_dir / candidate.filename
        try:
            result.size_bytes = client.download_to_file(candidate.url, raw_path)
            result.raw_path = raw_path
        except IgnServerUnavailableError as exc:
            result.error = f"Téléchargement impossible : {exc}"
            results.append(result)
            continue
        except Exception as exc:  # noqa: BLE001
            result.error = f"Erreur inattendue lors du téléchargement : {exc}"
            results.append(result)
            continue

        if process:
            try:
                result.processed_path = process_downloaded_file(raw_path, station_dir)
            except RinexProcessingError as exc:
                result.error = f"Fichier téléchargé mais non exploitable : {exc}"

        results.append(result)

    return results


@dataclass
class MergedDownloadResult:
    downloaded_files: list[DownloadedFile] = field(default_factory=list)
    merged_path: Path | None = None
    merge_error: str | None = None


def _hour_range_label(sessions: list[str]) -> str:
    if sessions == [DAILY_SESSION_CODE]:
        return "0000-2400"
    hours = sorted(session_letter_to_hour(s) for s in sessions)
    return f"{hours[0]:02d}00-{hours[-1] + 1:02d}00"


def _build_merged_filename(
    station: str, date: dt.date, candidates: list[RinexFileCandidate], keep_systems: set[str] | None
) -> str:
    yy = date.year % 100
    doy = day_of_year(date)
    sessions = sorted({c.session for c in candidates})
    suffix = f"_{''.join(sorted(keep_systems))}" if keep_systems else ""
    return f"{station.lower()}{doy:03d}_{_hour_range_label(sessions)}{suffix}.{yy:02d}o"


def download_and_merge_station_files(
    client: RgpHttpClient,
    candidates: list[RinexFileCandidate],
    station_dir: Path,
    date: dt.date,
    keep_systems: set[str] | None = None,
) -> MergedDownloadResult:
    """Télécharge les fichiers d'une station puis les fusionne en un seul fichier RINEX.

    La fusion (voir `app.rgp.rinex_merge`) n'est déclenchée que si elle apporte
    réellement quelque chose : plusieurs fichiers horaires à recombiner, ou un
    filtrage par constellation demandé. Dans le cas trivial (un seul fichier,
    aucun filtre), le fichier RINEX obtenu normalement est renvoyé tel quel.

    En cas d'échec de la fusion (ex. en-têtes incompatibles, ce qui ne devrait
    pas arriver pour une même station/journée), les fichiers individuels déjà
    téléchargés et convertis sont conservés plutôt que perdus, et l'erreur est
    remontée dans `merge_error` — jamais masquée (cahier des charges §11).
    """
    downloaded = download_station_files(client, candidates, station_dir, process=True)
    ok_files = [f for f in downloaded if f.ok and f.processed_path is not None]

    if not ok_files:
        return MergedDownloadResult(downloaded_files=downloaded)

    if len(ok_files) == 1 and keep_systems is None:
        return MergedDownloadResult(downloaded_files=downloaded, merged_path=ok_files[0].processed_path)

    station_code = candidates[0].station
    merged_candidates = [f.candidate for f in ok_files]
    merged_name = _build_merged_filename(station_code, date, merged_candidates, keep_systems)
    merged_path = station_dir / merged_name

    try:
        merge_rinex2_observation_files(
            sorted((f.processed_path for f in ok_files), key=lambda p: p.name), merged_path, keep_systems
        )
    except RinexMergeError as exc:
        return MergedDownloadResult(downloaded_files=downloaded, merge_error=str(exc))

    # Les fichiers horaires individuels sont désormais redondants avec le fichier fusionné.
    for f in ok_files:
        f.processed_path.unlink(missing_ok=True)

    return MergedDownloadResult(downloaded_files=downloaded, merged_path=merged_path)
