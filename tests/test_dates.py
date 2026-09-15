import datetime as dt

import pytest

from app.utils.dates import (
    day_of_year,
    hour_to_session_letter,
    local_range_to_utc,
    session_letters_for_range,
)


def test_day_of_year_known_dates():
    assert day_of_year(dt.date(2026, 1, 1)) == 1
    assert day_of_year(dt.date(2026, 9, 14)) == 257
    assert day_of_year(dt.date(2026, 12, 31)) == 365


def test_hour_to_session_letter():
    assert hour_to_session_letter(0) == "a"
    assert hour_to_session_letter(23) == "x"
    with pytest.raises(ValueError):
        hour_to_session_letter(24)


def test_session_letters_for_range_within_one_hour():
    start = dt.datetime(2026, 9, 14, 8, 15)
    end = dt.datetime(2026, 9, 14, 8, 45)
    assert session_letters_for_range(start, end) == ["i"]  # heure 8 -> lettre 'i'


def test_session_letters_for_range_spanning_hours():
    start = dt.datetime(2026, 9, 14, 8, 15)
    end = dt.datetime(2026, 9, 14, 17, 45)
    letters = session_letters_for_range(start, end)
    assert letters == list("ijklmnopqr")  # heures 8 à 17 inclus


def test_session_letters_end_on_exact_hour_boundary():
    start = dt.datetime(2026, 9, 14, 8, 0)
    end = dt.datetime(2026, 9, 14, 9, 0)
    # 9:00 pile ne nécessite pas l'heure 9-10.
    assert session_letters_for_range(start, end) == ["i"]


def test_session_letters_rejects_end_before_start():
    start = dt.datetime(2026, 9, 14, 9, 0)
    end = dt.datetime(2026, 9, 14, 8, 0)
    with pytest.raises(ValueError):
        session_letters_for_range(start, end)


def test_session_letters_rejects_multi_day_range():
    start = dt.datetime(2026, 9, 14, 23, 0)
    end = dt.datetime(2026, 9, 15, 1, 0)
    with pytest.raises(ValueError):
        session_letters_for_range(start, end)


def test_local_range_to_utc_summer_time_paris():
    # Mi-septembre : Paris est en UTC+2 (heure d'été).
    start_utc, end_utc = local_range_to_utc(
        dt.date(2026, 9, 14), dt.time(8, 15), dt.time(17, 45), full_day=False, timezone_name="Europe/Paris"
    )
    assert start_utc == dt.datetime(2026, 9, 14, 6, 15, tzinfo=dt.timezone.utc)
    assert end_utc == dt.datetime(2026, 9, 14, 15, 45, tzinfo=dt.timezone.utc)


def test_local_range_to_utc_full_day():
    start_utc, end_utc = local_range_to_utc(
        dt.date(2026, 9, 14), None, None, full_day=True, timezone_name="Europe/Paris"
    )
    assert start_utc == dt.datetime(2026, 9, 13, 22, 0, tzinfo=dt.timezone.utc)
    assert end_utc == dt.datetime(2026, 9, 14, 22, 0, tzinfo=dt.timezone.utc)


def test_local_range_to_utc_rejects_end_before_start():
    with pytest.raises(ValueError):
        local_range_to_utc(
            dt.date(2026, 9, 14), dt.time(17, 0), dt.time(8, 0), full_day=False, timezone_name="Europe/Paris"
        )
