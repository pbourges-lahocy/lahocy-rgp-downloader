"""Chargement de la configuration de l'application depuis config/config.yaml."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

_FROZEN = getattr(sys, "frozen", False)


def _app_root() -> Path:
    """Racine à partir de laquelle résoudre `config/config.yaml`.

    En exécution normale (source), c'est la racine du dépôt. Dans un exécutable
    PyInstaller (`sys.frozen`), `__file__` pointe dans l'archive extraite : on se base
    alors sur `sys._MEIPASS` (onefile) ou le dossier de l'exécutable (onedir), là où
    `--add-data` place effectivement `config/`.
    """
    if _FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[3]


_PROJECT_ROOT = _app_root()
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"


def _default_cache_root() -> Path:
    """Racine par défaut du cache si `cache.directory` (config.yaml) est relatif.

    En exécutable installé, on écrit dans le profil utilisateur (`%LOCALAPPDATA%`)
    plutôt qu'à côté de l'exécutable, qui peut se trouver dans un dossier en
    lecture seule (ex. Program Files) et est partagé entre utilisateurs Windows.
    En source, on garde le cache dans le dépôt pour rester simple à inspecter.
    """
    if _FROZEN:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "LahocyRGPDownloader"
    return _PROJECT_ROOT


@dataclass(frozen=True)
class IgnConfig:
    base_url: str
    data_dir: str
    data_v3_dir: str
    logsheet_dir: str
    cadences: tuple[int, ...]


@dataclass(frozen=True)
class NetworkConfig:
    timeout_seconds: float
    retries: int
    retry_backoff_seconds: float
    user_agent: str


@dataclass(frozen=True)
class CacheConfig:
    directory: str
    catalog_filename: str
    catalog_ttl_days: int


@dataclass(frozen=True)
class SelectionConfig:
    default_station_count: int
    default_cadence: int


@dataclass(frozen=True)
class AppConfig:
    ign: IgnConfig
    network: NetworkConfig
    cache: CacheConfig
    selection: SelectionConfig

    @property
    def cache_dir(self) -> Path:
        path = Path(self.cache.directory)
        if not path.is_absolute():
            path = _default_cache_root() / path
        return path


def load_config(path: Path | str | None = None) -> AppConfig:
    config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return AppConfig(
        ign=IgnConfig(
            base_url=raw["ign"]["base_url"].rstrip("/"),
            data_dir=raw["ign"]["data_dir"],
            data_v3_dir=raw["ign"]["data_v3_dir"],
            logsheet_dir=raw["ign"]["logsheet_dir"],
            cadences=tuple(raw["ign"]["cadences"]),
        ),
        network=NetworkConfig(
            timeout_seconds=float(raw["network"]["timeout_seconds"]),
            retries=int(raw["network"]["retries"]),
            retry_backoff_seconds=float(raw["network"]["retry_backoff_seconds"]),
            user_agent=raw["network"]["user_agent"],
        ),
        cache=CacheConfig(
            directory=raw["cache"]["directory"],
            catalog_filename=raw["cache"]["catalog_filename"],
            catalog_ttl_days=int(raw["cache"]["catalog_ttl_days"]),
        ),
        selection=SelectionConfig(
            default_station_count=int(raw["selection"]["default_station_count"]),
            default_cadence=int(raw["selection"]["default_cadence"]),
        ),
    )
