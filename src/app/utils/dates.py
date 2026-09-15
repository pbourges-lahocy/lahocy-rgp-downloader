"""Utilitaires de date/heure pour les chemins RINEX (jour de l'année, sessions horaires UTC)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

# Lettres de session horaire RINEX : 'a' = 0h-1h UTC, ..., 'x' = 23h-24h UTC.
_SESSION_LETTERS = "abcdefghijklmnopqrstuvwx"
DAILY_SESSION_CODE = "0"


def local_range_to_utc(
    date: dt.date,
    start_time: dt.time | None,
    end_time: dt.time | None,
    full_day: bool,
    timezone_name: str,
) -> tuple[dt.datetime, dt.datetime]:
    """Convertit une plage horaire locale (chantier) en plage UTC tz-aware.

    Le RGP publie exclusivement en UTC (voir docs/RGP_IGN.md §4) alors que
    l'utilisateur saisit une heure locale de chantier (métropole ou DOM-TOM,
    avec heure d'été/hiver) : cette conversion doit être faite une seule fois,
    ici, avant tout calcul de session RINEX.
    """
    tz = ZoneInfo(timezone_name)
    if full_day:
        local_start = dt.datetime.combine(date, dt.time.min, tzinfo=tz)
        local_end = dt.datetime.combine(date + dt.timedelta(days=1), dt.time.min, tzinfo=tz)
    else:
        if start_time is None or end_time is None:
            raise ValueError("Heure de début et de fin requises hors mode journée entière.")
        local_start = dt.datetime.combine(date, start_time, tzinfo=tz)
        local_end = dt.datetime.combine(date, end_time, tzinfo=tz)
        if local_end <= local_start:
            raise ValueError("L'heure de fin doit être postérieure à l'heure de début.")

    return local_start.astimezone(dt.timezone.utc), local_end.astimezone(dt.timezone.utc)


def day_of_year(date: dt.date) -> int:
    """Jour de l'année (1-366), tel qu'utilisé dans les chemins RGP (/AAAA/JJJ/)."""
    return date.timetuple().tm_yday


def hour_to_session_letter(hour_utc: int) -> str:
    """Convertit une heure UTC (0-23) en lettre de session RINEX ('a'-'x')."""
    if not 0 <= hour_utc <= 23:
        raise ValueError(f"Heure UTC invalide : {hour_utc}")
    return _SESSION_LETTERS[hour_utc]


def session_letters_for_range(start: dt.datetime, end: dt.datetime) -> list[str]:
    """Liste ordonnée des lettres de session horaire UTC couvrant [start, end].

    `start` et `end` doivent être en UTC (naïfs ou conscients) et sur le même jour,
    à une exception près : `end` peut être exactement minuit du jour suivant
    (marqueur de "fin de journée UTC", utile quand l'appelant a découpé une plage
    chevauchant deux jours — voir `app.rgp.availability.check_availability_for_utc_period`).
    Une borne de fin exactement sur une heure pleine (ex. 17:00) n'exige pas le
    fichier horaire suivant : la dernière heure retenue est celle contenant l'instant
    juste avant `end`.
    """
    if end <= start:
        raise ValueError("L'heure de fin doit être postérieure à l'heure de début.")

    is_next_day_midnight = end.date() == start.date() + dt.timedelta(days=1) and end.time() == dt.time.min
    if start.date() != end.date() and not is_next_day_midnight:
        raise ValueError("La plage horaire doit être contenue dans une seule journée UTC.")

    start_hour = start.hour
    if is_next_day_midnight:
        end_hour = 23
    else:
        end_hour = end.hour if end.minute > 0 or end.second > 0 else end.hour - 1
    end_hour = max(start_hour, end_hour)

    return [hour_to_session_letter(h) for h in range(start_hour, end_hour + 1)]
