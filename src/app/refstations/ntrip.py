"""Lecture des stations d'un caster NTRIP 2.0 à partir de sa table des mounts (sourcetable).

Le caster Centipède expose sa table en HTTPS (port 443, NTRIP 2.0 sur TLS — voir
https://docs.centipede-rtk.org/access.html) : on évite ainsi le port NTRIP historique
2101, souvent filtré sur les réseaux d'entreprise (vérifié : bloqué sur le poste de
développement alors que 443 répond).

Champs d'une ligne `STR` (spec NTRIP, séparateur ';') — positions vérifiées sur la
vraie table de `https://crtk.net/` (1304 lignes de 19 champs chacune) :
 0 STR | 1 mountpoint | 2 identifiant | 3 format | 4 détails du format | 5 porteuse |
 6 systèmes GNSS | 7 réseau | 8 pays | 9 latitude | 10 longitude | 11 NMEA |
 12 solution | 13 générateur | 14 compression | 15 authentification | 16 frais |
 17 débit | 18 divers (sous-réseau/organisme pour Centipède)
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from app.config.loader import NtripCasterConfig
from app.refstations.models import ReferenceStation
from app.utils.http_client import IgnServerUnavailableError, RgpHttpClient

NTRIP_HEADERS = {"Ntrip-Version": "Ntrip/2.0", "User-Agent": "NTRIP Lahocy-RGP-Downloader/0.2"}
_MIN_STR_FIELDS = 11


class NtripError(RuntimeError):
    """Table des mounts inexploitable (vide ou illisible)."""


def parse_sourcetable(
    text: str, source_id: str, virtual_mounts: tuple[str, ...] = ()
) -> tuple[list[ReferenceStation], list[str]]:
    """Extrait les stations d'une sourcetable. Retourne (stations, lignes ignorées avec motif)."""
    stations: list[ReferenceStation] = []
    skipped: list[str] = []
    virtual = {m.upper() for m in virtual_mounts}

    for line in text.splitlines():
        if not line.startswith("STR;"):
            continue
        fields = line.split(";")
        mount = fields[1] if len(fields) > 1 else "?"
        if len(fields) < _MIN_STR_FIELDS:
            skipped.append(f"{mount} : ligne trop courte ({len(fields)} champs)")
            continue
        if mount.upper() in virtual:
            continue  # mount virtuel (ex. NEAR) : pas une antenne physique
        try:
            lat, lon = float(fields[9]), float(fields[10])
        except ValueError:
            skipped.append(f"{mount} : coordonnées illisibles ({fields[9]!r}, {fields[10]!r})")
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            skipped.append(f"{mount} : coordonnées invraisemblables ({lat}, {lon})")
            continue

        # Beaucoup de bases Centipède n'ont pour identifiant que leur code pays : pas un vrai nom.
        name = "" if fields[2] in ("", fields[8]) else fields[2]
        network = fields[7] if fields[7] not in ("", "NONE") else (fields[18] if len(fields) > 18 else "")
        stations.append(
            ReferenceStation(
                source_id=source_id,
                code=mount,
                name=name,
                latitude=lat,
                longitude=lon,
                country=fields[8],
                network=network,
                constellations=fields[6],
            )
        )
    return stations, skipped


@dataclass
class NtripLoadResult:
    stations: list[ReferenceStation]
    warnings: list[str] = field(default_factory=list)
    from_cache: bool = False
    stale: bool = False


def _cache_path(cache_dir: Path, caster_id: str) -> Path:
    return cache_dir / f"ntrip_{caster_id}_sourcetable.json"


def _read_cache(path: Path, ttl_days: float | None) -> list[ReferenceStation] | None:
    if not path.exists():
        return None
    if ttl_days is not None and (time.time() - path.stat().st_mtime) / 86400 > ttl_days:
        return None
    with path.open("r", encoding="utf-8") as f:
        return [ReferenceStation(**item) for item in json.load(f)]


def _write_cache(path: Path, stations: list[ReferenceStation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in stations], f, ensure_ascii=False)


def load_ntrip_stations(
    client: RgpHttpClient,
    caster: NtripCasterConfig,
    cache_dir: Path,
    ttl_days: float,
    force_refresh: bool = False,
) -> NtripLoadResult:
    """Stations d'un caster : cache frais si possible, sinon réseau.

    Si le caster est injoignable mais qu'une ancienne liste est en cache, on l'utilise
    en le signalant explicitement (les positions des bases changent rarement) plutôt
    que de laisser l'utilisateur sans carte ; sans cache, l'erreur est remontée.
    """
    path = _cache_path(cache_dir, caster.id)
    if not force_refresh:
        cached = _read_cache(path, ttl_days)
        if cached is not None:
            return NtripLoadResult(stations=cached, from_cache=True)

    try:
        text = client.get_text(caster.sourcetable_url, headers=NTRIP_HEADERS)
    except (IgnServerUnavailableError, httpx.HTTPStatusError) as exc:
        stale = _read_cache(path, None)
        if stale is None:
            raise
        age_days = (time.time() - path.stat().st_mtime) / 86400
        return NtripLoadResult(
            stations=stale,
            warnings=[
                f"{caster.name} injoignable ({exc}) : liste en cache de {age_days:.0f} jour(s) utilisée."
            ],
            from_cache=True,
            stale=True,
        )

    stations, skipped = parse_sourcetable(text, caster.id, caster.virtual_mounts)
    if not stations:
        raise NtripError(f"La table des mounts de {caster.name} ({caster.sourcetable_url}) ne contient aucune station exploitable.")
    _write_cache(path, stations)

    warnings = [f"{caster.name} : {len(skipped)} mount(s) ignoré(s) ({'; '.join(skipped[:3])}...)"] if skipped else []
    return NtripLoadResult(stations=stations, warnings=warnings)
