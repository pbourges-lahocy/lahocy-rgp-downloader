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

État en ligne / hors ligne — il n'existe PAS de champ dédié dans la table. Ce qui est
établi (code du caster, github.com/pbeyssac/millipede-caster, caster/sourcetable.c) : pour
les bases du caster lui-même, une entrée n'est servie que si la base est connectée
(`livesource_exists`) ; cette règle ne vaut pas pour les entrées importées d'autres casters.
Sur la table réelle, ces dernières se distinguent nettement : 1278 mounts natifs
(authentification `N`, réseau `NONE`) et 26 mounts fédérés RENAG (authentification `B`).
  - natif listé            -> en ligne ;
  - fédéré (RENAG...)      -> état inconnu ;
  - natif déjà vu, absent  -> hors ligne (grâce à l'historique local, voir `load_ntrip_stations`) ;
  - caster injoignable     -> état inconnu pour tout (on ne prétend rien).
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config.loader import NtripCasterConfig
from app.refstations.models import STATUS_OFFLINE, STATUS_ONLINE, STATUS_UNKNOWN, ReferenceStation
from app.utils.http_client import IgnServerUnavailableError, RgpHttpClient

NTRIP_HEADERS = {"Ntrip-Version": "Ntrip/2.0", "User-Agent": "NTRIP Lahocy-RGP-Downloader/0.2"}
_MIN_STR_FIELDS = 11
_NATIVE_AUTH = "N"


class NtripError(RuntimeError):
    """Table des mounts inexploitable (vide ou illisible)."""


def _is_native(fields: list[str]) -> bool:
    network = fields[7]
    auth = fields[15] if len(fields) > 15 else ""
    return auth == _NATIVE_AUTH and network in ("", "NONE")


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
        if _is_native(fields):
            status = STATUS_ONLINE
            detail = "Base connectée au caster (présente dans la table des mounts)."
        else:
            status = STATUS_UNKNOWN
            detail = (
                f"Base fédérée ({fields[7] or 'autre caster'}) : la table des mounts ne permet "
                "pas de savoir si elle est connectée."
            )
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
                status=status,
                status_detail=detail,
            )
        )
    return stations, skipped


# --------------------------------------------------------------------------- cache + historique


@dataclass
class _Cache:
    fetched_at: float
    records: list[dict]  # champs de ReferenceStation + "last_seen"


def _read_cache(path: Path) -> _Cache | None:
    """Cache illisible ou d'un ancien format : traité comme absent plutôt que de planter."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return _Cache(fetched_at=float(data["fetched_at"]), records=list(data["stations"]))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write_cache(path: Path, fetched_at: float, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"fetched_at": fetched_at, "stations": records}, f, ensure_ascii=False)


def _station_from_record(record: dict) -> ReferenceStation:
    names = {f.name for f in dataclasses.fields(ReferenceStation)}
    return ReferenceStation(**{k: v for k, v in record.items() if k in names})


def _record(station: ReferenceStation, last_seen: float) -> dict:
    return {**dataclasses.asdict(station), "last_seen": last_seen}


def _merge_history(
    current: list[ReferenceStation], previous: list[dict], now: float, retention_days: float
) -> tuple[list[ReferenceStation], list[dict]]:
    """Ajoute à la liste courante les bases déjà vues mais absentes de la table : hors ligne.

    Seules les bases dont on pouvait connaître l'état (en ligne/hors ligne, donc natives)
    sont conservées, et seulement `retention_days` jours après leur dernière apparition.
    """
    present = {s.code for s in current}
    stations = list(current)
    records = [_record(s, now) for s in current]
    for rec in previous:
        if rec["code"] in present or rec.get("status") not in (STATUS_ONLINE, STATUS_OFFLINE):
            continue
        last_seen = float(rec.get("last_seen", 0))
        if now - last_seen > retention_days * 86400:
            continue
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(last_seen))
        offline = dataclasses.replace(
            _station_from_record(rec),
            status=STATUS_OFFLINE,
            status_detail=f"Hors ligne : n'est plus listée par le caster (dernière vue le {when}).",
        )
        stations.append(offline)
        records.append(_record(offline, last_seen))
    return stations, records


@dataclass
class NtripLoadResult:
    stations: list[ReferenceStation]
    warnings: list[str] = field(default_factory=list)
    from_cache: bool = False
    stale: bool = False
    fetched_at: float = 0.0


def load_ntrip_stations(
    client: RgpHttpClient,
    caster: NtripCasterConfig,
    cache_dir: Path,
    ttl_minutes: float,
    retention_days: float,
    force_refresh: bool = False,
    now: float | None = None,
) -> NtripLoadResult:
    """Stations d'un caster, avec leur état.

    Cache frais (`ttl_minutes`) si possible, sinon réseau. Chaque lecture réussie met à
    jour un historique local : une base déjà vue qui n'est plus listée apparaît « hors
    ligne » pendant `retention_days` jours (la table seule ne liste jamais les absentes).
    Si le caster est injoignable mais qu'une liste existe en cache, on l'utilise avec
    TOUS les états remis à « inconnu » et un avertissement explicite ; sans cache,
    l'erreur est remontée.
    """
    now = time.time() if now is None else now
    path = cache_dir / f"ntrip_{caster.id}_sourcetable.json"
    cache = _read_cache(path)

    if cache is not None and not force_refresh and now - cache.fetched_at <= ttl_minutes * 60:
        return NtripLoadResult(
            stations=[_station_from_record(r) for r in cache.records], from_cache=True, fetched_at=cache.fetched_at
        )

    try:
        text = client.get_text(caster.sourcetable_url, headers=NTRIP_HEADERS)
    except (IgnServerUnavailableError, httpx.HTTPStatusError) as exc:
        if cache is None:
            raise
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(cache.fetched_at))
        unknown = [
            dataclasses.replace(
                _station_from_record(r),
                status=STATUS_UNKNOWN,
                status_detail=f"Caster injoignable : état inconnu (liste du {when}).",
            )
            for r in cache.records
        ]
        return NtripLoadResult(
            stations=unknown,
            warnings=[f"{caster.name} injoignable ({exc}) : liste du {when} utilisée, états inconnus."],
            from_cache=True,
            stale=True,
            fetched_at=cache.fetched_at,
        )

    current, skipped = parse_sourcetable(text, caster.id, caster.virtual_mounts)
    if not current:
        raise NtripError(
            f"La table des mounts de {caster.name} ({caster.sourcetable_url}) ne contient aucune station exploitable."
        )
    stations, records = _merge_history(current, cache.records if cache else [], now, retention_days)
    _write_cache(path, now, records)

    warnings = [f"{caster.name} : {len(skipped)} mount(s) ignoré(s) ({'; '.join(skipped[:3])}...)"] if skipped else []
    return NtripLoadResult(stations=stations, warnings=warnings, fetched_at=now)
