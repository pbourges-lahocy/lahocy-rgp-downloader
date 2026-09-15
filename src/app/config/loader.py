"""Chargement de la configuration de l'application depuis config/config.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"


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
            path = _PROJECT_ROOT / path
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
