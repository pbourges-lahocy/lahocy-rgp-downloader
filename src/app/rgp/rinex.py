"""Décompression et conversion des fichiers RINEX/CRINEX du RGP.

Ne réimplémente aucun algorithme de compression :
- `.Z`  (UNIX compress/LZW, utilisé par RINEX 2) -> bibliothèque pure Python `unlzw3`.
- `.gz` (gzip, utilisé par RINEX 3)              -> module standard `gzip`.
- CRINEX/Hatanaka (`.d`/`.crx`) -> RINEX observation -> bibliothèque `hatanaka`,
  qui s'appuie sur les exécutables officiels RNXCMP de Y. Hatanaka / GSI.

Voir docs/RGP_IGN.md §6 pour la justification de ces choix.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import hatanaka
import unlzw3


class RinexProcessingError(RuntimeError):
    """La décompression ou la conversion d'un fichier RINEX a échoué."""


def decompress_unix_z(source: Path, destination: Path) -> Path:
    """Décompresse un fichier `.Z` (UNIX compress/LZW)."""
    try:
        data = unlzw3.unlzw(source.read_bytes())
    except Exception as exc:  # noqa: BLE001
        raise RinexProcessingError(f"Échec de décompression .Z pour {source} : {exc}") from exc
    destination.write_bytes(data)
    return destination


def decompress_gzip(source: Path, destination: Path) -> Path:
    """Décompresse un fichier `.gz`."""
    try:
        with gzip.open(source, "rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    except OSError as exc:
        raise RinexProcessingError(f"Échec de décompression .gz pour {source} : {exc}") from exc
    return destination


def decompress(source: Path, destination: Path) -> Path:
    """Décompresse selon l'extension (`.Z` ou `.gz`)."""
    suffix = source.suffix.lower()
    if suffix == ".z":
        return decompress_unix_z(source, destination)
    if suffix == ".gz":
        return decompress_gzip(source, destination)
    raise RinexProcessingError(f"Extension de compression non reconnue : {source.name!r}")


def hatanaka_to_rinex(source: Path, destination: Path) -> Path:
    """Convertit un fichier CRINEX (Hatanaka, `.d` ou `.crx` décompressé) en RINEX observation."""
    try:
        decompressed_text = hatanaka.decompress(source)
    except Exception as exc:  # noqa: BLE001
        raise RinexProcessingError(f"Échec de conversion Hatanaka pour {source} : {exc}") from exc
    destination.write_bytes(decompressed_text)
    return destination


def process_downloaded_file(source: Path, output_dir: Path) -> Path:
    """Pipeline complet : décompresse puis convertit Hatanaka si nécessaire.

    `source` est le fichier tel que téléchargé (ex. `aaer257a.26d.Z`).
    Retourne le chemin du fichier RINEX final directement exploitable.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    is_compressed = source.suffix.lower() in (".z", ".gz")
    if is_compressed:
        decompressed_name = source.stem  # retire .Z ou .gz
        decompressed_path = output_dir / decompressed_name
        decompress(source, decompressed_path)
    else:
        decompressed_path = source

    is_hatanaka = decompressed_path.suffix.lower() in (".d", ".crx")
    if is_hatanaka:
        final_name = _rinex_observation_name(decompressed_path.name)
        final_path = output_dir / final_name
        hatanaka_to_rinex(decompressed_path, final_path)
        if decompressed_path != source:
            decompressed_path.unlink(missing_ok=True)
        return final_path

    return decompressed_path


def _rinex_observation_name(hatanaka_filename: str) -> str:
    """Déduit le nom RINEX observation standard à partir d'un nom CRINEX.

    RINEX 2 : ssssjjjh.aad -> ssssjjjh.aao
    RINEX 3 : ..._MO.crx   -> ..._MO.rnx
    """
    if hatanaka_filename.lower().endswith(".crx"):
        return hatanaka_filename[: -len(".crx")] + ".rnx"
    if hatanaka_filename[-1:].lower() == "d":
        return hatanaka_filename[:-1] + "o"
    return hatanaka_filename
