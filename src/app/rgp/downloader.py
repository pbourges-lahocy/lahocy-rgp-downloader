"""Téléchargement réel des fichiers RINEX sélectionnés vers le dossier du chantier.

Produit, pour chaque station, un dossier contenant à la fois les fichiers
téléchargés tels quels et leur version RINEX directement exploitable
(décompressée et, si besoin, convertie depuis Hatanaka), en conservant le
nom RINEX standard plutôt qu'un nom générique (cahier des charges §8).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.rgp.provider_ign import RinexFileCandidate
from app.rgp.rinex import RinexProcessingError, process_downloaded_file
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
