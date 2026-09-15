"""Construction et mise en cache du catalogue des stations RGP.

Le serveur IGN ne publie pas de catalogue consolidé : il faut agréger les
fiches de site individuelles (`logsheet/*.log`, format IGS Site Log v2.0).
Voir docs/RGP_IGN.md §2.3. Le résultat est mis en cache localement (JSON)
pour permettre à l'application de démarrer sans dépendre du réseau
(cahier des charges §14), avec une actualisation explicite possible.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from app.geo.coordinates import parse_igs_sexagesimal
from app.rgp.provider_ign import IgnProviderIGN
from app.rgp.stations import Station
from app.utils.http_client import RgpHttpClient

_LOGSHEET_LINK_RE = re.compile(r'href="([a-zA-Z0-9_]+\.log)"')

# Plage large couvrant la métropole, la Corse et les DOM-TOM (Antilles, Guyane,
# Réunion/Mayotte, Nouvelle-Calédonie, Polynésie, Saint-Pierre-et-Miquelon).
# Sert uniquement de garde-fou contre des fiches de site corrompues (observé en
# pratique : quelques fiches RGP contiennent des valeurs manifestement erronées,
# ex. une latitude de 74°N) — pas une frontière géographique stricte.
_PLAUSIBLE_LATITUDE = (-23.0, 51.5)
_PLAUSIBLE_LONGITUDE = (-179.0, 179.0)


def list_logsheet_filenames(client: RgpHttpClient, provider: IgnProviderIGN) -> list[str]:
    """Récupère la liste des fiches de site disponibles depuis la page d'index Apache."""
    html = client.get_text(provider.logsheet_index_url())
    return sorted(set(_LOGSHEET_LINK_RE.findall(html)))


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _current_satellite_system(text: str) -> str:
    values = re.findall(r"^\s*Satellite System\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    real_values = [v for v in values if v and "(" not in v]
    return real_values[-1] if real_values else "Inconnu"


def parse_logsheet(text: str, filename: str) -> Station:
    """Extrait une Station à partir du contenu texte d'une fiche de site IGS."""
    site_id9 = _field(text, "Nine Character ID")
    if not site_id9:
        raise ValueError(f"Fiche de site sans identifiant 9 caractères ({filename!r}).")

    lat_raw = _field(text, "Latitude (N is +)")
    lon_raw = _field(text, "Longitude (E is +)")
    elev_raw = _field(text, "Elevation (m,ellips.)")
    if not lat_raw or not lon_raw:
        raise ValueError(f"Fiche de site sans coordonnées exploitables ({filename!r}).")

    latitude = parse_igs_sexagesimal(lat_raw)
    longitude = parse_igs_sexagesimal(lon_raw)
    if not (_PLAUSIBLE_LATITUDE[0] <= latitude <= _PLAUSIBLE_LATITUDE[1]) or not (
        _PLAUSIBLE_LONGITUDE[0] <= longitude <= _PLAUSIBLE_LONGITUDE[1]
    ):
        raise ValueError(
            f"Coordonnées invraisemblables pour une station RGP ({filename!r}) : "
            f"lat={latitude}, lon={longitude} — fiche probablement corrompue, ignorée."
        )

    return Station(
        code=site_id9[:4].lower(),
        site_id9=site_id9,
        name=_field(text, "Site Name") or site_id9,
        city=_field(text, "City or Town") or "",
        country=_field(text, "Country or Region") or site_id9[6:9],
        latitude=latitude,
        longitude=longitude,
        elevation_m=float(elev_raw) if elev_raw else 0.0,
        satellite_system=_current_satellite_system(text),
        logsheet_filename=filename,
    )


def _cache_path(cache_dir: Path, filename: str) -> Path:
    return cache_dir / filename


def load_cached_catalog(cache_dir: Path, catalog_filename: str, ttl_days: int) -> list[Station] | None:
    """Charge le catalogue en cache s'il existe et n'a pas expiré, sinon None."""
    path = _cache_path(cache_dir, catalog_filename)
    if not path.exists():
        return None

    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > ttl_days:
        return None

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Station(**item) for item in raw]


def save_catalog_to_cache(cache_dir: Path, catalog_filename: str, stations: list[Station]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, catalog_filename)
    with path.open("w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in stations], f, ensure_ascii=False, indent=2)


def build_catalog_from_network(
    client: RgpHttpClient, provider: IgnProviderIGN, on_progress: callable | None = None
) -> tuple[list[Station], list[str]]:
    """Télécharge et parse toutes les fiches de site. Retourne (stations, erreurs)."""
    filenames = list_logsheet_filenames(client, provider)
    stations: list[Station] = []
    errors: list[str] = []

    for i, filename in enumerate(filenames, start=1):
        try:
            text = client.get_text(provider.logsheet_url(filename))
            stations.append(parse_logsheet(text, filename))
        except Exception as exc:  # noqa: BLE001 - on veut continuer malgré une fiche corrompue
            errors.append(f"{filename}: {exc}")
        if on_progress:
            on_progress(i, len(filenames))

    return stations, errors


def get_catalog(
    client: RgpHttpClient,
    provider: IgnProviderIGN,
    cache_dir: Path,
    catalog_filename: str,
    ttl_days: int,
    force_refresh: bool = False,
    on_progress: callable | None = None,
) -> list[Station]:
    """Point d'entrée principal : cache si valide, sinon reconstruction depuis le réseau."""
    if not force_refresh:
        cached = load_cached_catalog(cache_dir, catalog_filename, ttl_days)
        if cached is not None:
            return cached

    stations, errors = build_catalog_from_network(client, provider, on_progress)
    if errors:
        import logging

        logging.getLogger(__name__).warning(
            "%d fiche(s) de site n'ont pas pu être analysées : %s", len(errors), errors
        )
    save_catalog_to_cache(cache_dir, catalog_filename, stations)
    return stations
