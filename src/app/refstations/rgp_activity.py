"""Activité des stations RGP, mesurée sur les fichiers réellement publiés par l'IGN.

Le catalogue (fiches de site) ne dit pas si une station émet encore ; il n'existe pas de
champ « actif » côté IGN. On teste donc ce qui compte vraiment pour l'utilisateur : la
station a-t-elle PUBLIÉ son dernier fichier horaire sur `rgpdata.ign.fr` ?

L'IGN publie le fichier de l'heure [H, H+1[ vers H+1h03 (observé : `aaer257a` modifié à
01:03, voir docs/RGP_IGN.md §4). On interroge donc l'heure la plus récente terminée depuis
au moins 90 minutes, ce qui laisse une marge à la publication. Fichier présent (cadence 30 s,
sinon 1 s) -> active ; absent -> inactive (panne, retard de publication, station arrêtée OU station
jamais diffusée publiquement — la requête ne permet pas de distinguer ; ~38 % du catalogue n'avait
aucune donnée publique la veille de la mesure et seules 20 à 58 de ces stations apparaissent dans
les données publiques sur 6 dates échantillonnées entre J-1 et J-730) ; serveur injoignable -> état inconnu, jamais « inactive ».
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.refstations.models import STATUS_OFFLINE, STATUS_ONLINE, STATUS_UNKNOWN, ReferenceStation
from app.rgp.provider_ign import IgnProviderIGN
from app.utils.dates import hour_to_session_letter
from app.utils.http_client import IgnServerUnavailableError, RgpHttpClient

PUBLICATION_MARGIN = dt.timedelta(minutes=90)
_CACHE_NAME = "rgp_activity.json"


def latest_published_hour(now_utc: dt.datetime) -> dt.datetime:
    """Début (UTC) de l'heure la plus récente dont la publication est très probablement faite."""
    return (now_utc - PUBLICATION_MARGIN).replace(minute=0, second=0, microsecond=0)


@dataclass
class ActivityResult:
    hour_utc: dt.datetime
    active: dict[str, bool]  # code (minuscule) -> publié ? ; absent = non vérifiable
    checked_at: float


def _is_active(client: RgpHttpClient, provider: IgnProviderIGN, code: str, hour: dt.datetime, cadences) -> bool | None:
    letter = hour_to_session_letter(hour.hour)
    try:
        for cadence in cadences:
            candidate = provider.rinex2_candidate(code, hour.date(), letter, cadence)
            if client.head(candidate.url).exists:
                return True
        return False
    except IgnServerUnavailableError:
        return None


def check_rgp_activity(
    client: RgpHttpClient,
    provider: IgnProviderIGN,
    codes: list[str],
    hour: dt.datetime,
    cadences: tuple[int, ...] = (30, 1),
    max_workers: int = 8,
) -> dict[str, bool]:
    unique = sorted({c.lower() for c in codes})
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        outcomes = list(pool.map(lambda c: _is_active(client, provider, c, hour, cadences), unique))
    return {code: ok for code, ok in zip(unique, outcomes) if ok is not None}


def load_rgp_activity(
    client: RgpHttpClient,
    provider: IgnProviderIGN,
    codes: list[str],
    cache_dir: Path,
    ttl_minutes: float,
    cadences: tuple[int, ...],
    force_refresh: bool = False,
    now_utc: dt.datetime | None = None,
) -> ActivityResult:
    """Activité du RGP, avec un cache court : ~770 stations = autant de requêtes HEAD à l'IGN."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    hour = latest_published_hour(now_utc)
    path = cache_dir / _CACHE_NAME
    wanted = {c.lower() for c in codes}

    if not force_refresh:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            fresh = now_utc.timestamp() - float(data["checked_at"]) <= ttl_minutes * 60
            if fresh and data["hour"] == hour.isoformat() and wanted <= set(data["active"]):
                return ActivityResult(hour, {k: bool(v) for k, v in data["active"].items()}, float(data["checked_at"]))
        except (OSError, ValueError, TypeError, KeyError):
            pass  # cache absent/illisible : on mesure

    active = check_rgp_activity(client, provider, list(wanted), hour, cadences)
    checked_at = now_utc.timestamp()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"checked_at": checked_at, "hour": hour.isoformat(), "active": active}, f)
    return ActivityResult(hour, active, checked_at)


def apply_rgp_activity(stations: list[ReferenceStation], result: ActivityResult) -> list[ReferenceStation]:
    span = f"{result.hour_utc.hour:02d}h–{(result.hour_utc.hour + 1) % 24:02d}h UTC"
    updated = []
    for s in stations:
        verdict = result.active.get(s.code.lower())
        if verdict is True:
            updated.append(dataclasses.replace(
                s, status=STATUS_ONLINE, status_detail=f"Données publiées par l'IGN pour l'heure {span}."
            ))
        elif verdict is False:
            updated.append(dataclasses.replace(
                s,
                status=STATUS_OFFLINE,
                status_detail=(
                    f"Aucune donnée publique publiée par l'IGN pour l'heure {span} : panne, retard de "
                    "publication, station arrêtée ou station non diffusée publiquement (nombreuses dans le catalogue)."
                ),
            ))
        else:
            updated.append(dataclasses.replace(
                s, status=STATUS_UNKNOWN, status_detail="Activité non vérifiée (serveur IGN injoignable)."
            ))
    return updated
