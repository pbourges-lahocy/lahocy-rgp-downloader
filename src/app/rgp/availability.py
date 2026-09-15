"""Vérification de la disponibilité réelle des fichiers RINEX pour une station.

Principe fondamental du projet : ne jamais présenter une station comme
disponible uniquement parce qu'elle existe dans le catalogue. Chaque fichier
annoncé ici a été confirmé par une requête HTTP réelle sur le serveur IGN.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum

from app.rgp.provider_ign import OBSERVATION, IgnProviderIGN, RinexFileCandidate
from app.utils.http_client import RgpHttpClient


class AvailabilityStatus(str, Enum):
    DISPONIBLE = "disponible"
    PARTIEL = "partiel"
    INDISPONIBLE = "indisponible"


@dataclass
class AvailabilityResult:
    station_code: str
    requested_cadence: int
    status: AvailabilityStatus
    files: list[RinexFileCandidate] = field(default_factory=list)
    missing_sessions: list[str] = field(default_factory=list)
    used_daily_fallback: bool = False
    available_alternative_cadence: int | None = None
    warnings: list[str] = field(default_factory=list)
    total_size_bytes: int = 0


def _existing(client: RgpHttpClient, candidates: list[RinexFileCandidate]) -> tuple[list[RinexFileCandidate], list[RinexFileCandidate], int]:
    present: list[RinexFileCandidate] = []
    missing: list[RinexFileCandidate] = []
    total_size = 0
    for candidate in candidates:
        result = client.head(candidate.url)
        if result.exists:
            present.append(candidate)
            total_size += result.size_bytes or 0
        else:
            missing.append(candidate)
    return present, missing, total_size


def check_availability(
    client: RgpHttpClient,
    provider: IgnProviderIGN,
    station_code: str,
    date: dt.date,
    start_utc: dt.datetime,
    end_utc: dt.datetime,
    full_day: bool,
    cadence: int,
    other_cadences: tuple[int, ...] = (),
) -> AvailabilityResult:
    """Détermine exactement quels fichiers seraient téléchargés pour cette station.

    Stratégie (voir docs/RGP_IGN.md §4) :
    1. Journée entière -> on tente directement le fichier journalier.
    2. Plage horaire -> on tente les fichiers horaires couvrant la plage ;
       s'il en manque, on retombe sur le fichier journalier (avec avertissement)
       s'il existe, sinon on signale les heures manquantes.
    3. Si rien n'est disponible à la cadence demandée, on regarde si une autre
       cadence connue l'est, pour orienter l'utilisateur (cf. cahier des charges §11).
    """
    result = AvailabilityResult(
        station_code=station_code, requested_cadence=cadence, status=AvailabilityStatus.INDISPONIBLE
    )

    if full_day:
        daily = provider.daily_candidate(station_code, date, cadence, OBSERVATION)
        present, _missing, size = _existing(client, [daily])
        if present:
            result.status = AvailabilityStatus.DISPONIBLE
            result.files = present
            result.total_size_bytes = size
        else:
            result.status = AvailabilityStatus.INDISPONIBLE
    else:
        hourly = provider.hourly_candidates_for_range(station_code, start_utc, end_utc, cadence, OBSERVATION)
        present, missing, size = _existing(client, hourly)

        if not missing:
            result.status = AvailabilityStatus.DISPONIBLE
            result.files = present
            result.total_size_bytes = size
        else:
            daily = provider.daily_candidate(station_code, date, cadence, OBSERVATION)
            daily_present, _daily_missing, daily_size = _existing(client, [daily])
            if daily_present:
                result.status = AvailabilityStatus.DISPONIBLE
                result.files = daily_present
                result.total_size_bytes = daily_size
                result.used_daily_fallback = True
                result.missing_sessions = [c.session for c in missing]
                result.warnings.append(
                    f"Fichiers horaires incomplets pour {station_code.upper()} "
                    f"(heures manquantes : {', '.join(result.missing_sessions)}) — "
                    "le fichier journalier complet a été utilisé à la place."
                )
            elif present:
                result.status = AvailabilityStatus.PARTIEL
                result.files = present
                result.total_size_bytes = size
                result.missing_sessions = [c.session for c in missing]
                result.warnings.append(
                    f"Données partielles pour {station_code.upper()} : "
                    f"heures manquantes {', '.join(result.missing_sessions)}."
                )
            else:
                result.status = AvailabilityStatus.INDISPONIBLE

    if result.status == AvailabilityStatus.INDISPONIBLE:
        for alt_cadence in other_cadences:
            if alt_cadence == cadence:
                continue
            if full_day:
                alt_candidate = provider.daily_candidate(station_code, date, alt_cadence, OBSERVATION)
                alt_candidates = [alt_candidate]
            else:
                alt_candidates = provider.hourly_candidates_for_range(
                    station_code, start_utc, end_utc, alt_cadence, OBSERVATION
                )
            alt_present, _alt_missing, _alt_size = _existing(client, alt_candidates)
            if alt_present:
                result.available_alternative_cadence = alt_cadence
                result.warnings.append(
                    f"Les données {cadence}s de {station_code.upper()} ne sont pas disponibles "
                    f"pour cette période. Les données {alt_cadence}s sont disponibles."
                )
                break

    return result


def _split_utc_range_by_date(
    start_utc: dt.datetime, end_utc: dt.datetime
) -> list[tuple[dt.date, dt.datetime, dt.datetime]]:
    """Découpe [start_utc, end_utc) en segments ne dépassant jamais une journée UTC.

    Nécessaire car une plage horaire ou une "journée entière" saisie en heure locale
    (France métropolitaine ou DOM-TOM) peut chevaucher deux dates calendaires UTC
    (voir docs/RGP_IGN.md §4 : "Toutes les heures sont en UTC").
    """
    segments: list[tuple[dt.date, dt.datetime, dt.datetime]] = []
    cursor = start_utc
    while cursor < end_utc:
        next_midnight = dt.datetime.combine(
            cursor.date() + dt.timedelta(days=1), dt.time.min, tzinfo=cursor.tzinfo
        )
        segment_end = min(end_utc, next_midnight)
        segments.append((cursor.date(), cursor, segment_end))
        cursor = segment_end
    return segments


def _merge_results(results: list[AvailabilityResult]) -> AvailabilityResult:
    if len(results) == 1:
        return results[0]

    statuses = {r.status for r in results}
    if statuses == {AvailabilityStatus.DISPONIBLE}:
        merged_status = AvailabilityStatus.DISPONIBLE
    elif statuses == {AvailabilityStatus.INDISPONIBLE}:
        merged_status = AvailabilityStatus.INDISPONIBLE
    else:
        merged_status = AvailabilityStatus.PARTIEL

    return AvailabilityResult(
        station_code=results[0].station_code,
        requested_cadence=results[0].requested_cadence,
        status=merged_status,
        files=[f for r in results for f in r.files],
        missing_sessions=[s for r in results for s in r.missing_sessions],
        used_daily_fallback=any(r.used_daily_fallback for r in results),
        available_alternative_cadence=next(
            (r.available_alternative_cadence for r in results if r.available_alternative_cadence), None
        ),
        warnings=[w for r in results for w in r.warnings],
        total_size_bytes=sum(r.total_size_bytes for r in results),
    )


def check_availability_for_utc_period(
    client: RgpHttpClient,
    provider: IgnProviderIGN,
    station_code: str,
    start_utc: dt.datetime,
    end_utc: dt.datetime,
    full_day: bool,
    cadence: int,
    other_cadences: tuple[int, ...] = (),
) -> AvailabilityResult:
    """Comme `check_availability`, mais accepte une plage UTC chevauchant plusieurs jours.

    C'est la fonction à utiliser depuis l'interface (CLI ou GUI) une fois l'heure
    locale du chantier convertie en UTC : elle découpe automatiquement la période
    par date calendaire UTC et fusionne les résultats par station.

    Si `full_day` est vrai, chaque date UTC touchée par la journée locale reçoit
    son propre fichier journalier complet (une "journée entière" locale peut donc
    nécessiter les fichiers journaliers de deux dates UTC consécutives près de minuit).
    """
    segments = _split_utc_range_by_date(start_utc, end_utc)
    per_segment_results = []

    for seg_date, seg_start, seg_end in segments:
        spans_full_utc_day = seg_start.time() == dt.time.min and (seg_end - seg_start) >= dt.timedelta(hours=24)
        per_segment_results.append(
            check_availability(
                client,
                provider,
                station_code,
                seg_date,
                seg_start,
                seg_end,
                full_day=full_day or spans_full_utc_day,
                cadence=cadence,
                other_cadences=other_cadences,
            )
        )

    merged = _merge_results(per_segment_results)
    if len({seg[0] for seg in segments}) > 1:
        merged.warnings.append(
            f"La période demandée pour {station_code.upper()} chevauche deux journées UTC "
            f"({segments[0][0].isoformat()} et {segments[-1][0].isoformat()}) : "
            "plusieurs fichiers ont été nécessaires pour couvrir la période locale complète."
        )
    return merged
