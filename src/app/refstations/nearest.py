"""Recherche des antennes de référence les plus proches d'une position."""

from __future__ import annotations

from app.geo.distance import distance_km
from app.refstations.models import ReferenceDistance, ReferenceStation


def nearest_reference_stations(
    stations: list[ReferenceStation], lat: float, lon: float, limit: int
) -> list[ReferenceDistance]:
    """Les `limit` stations les plus proches (distance géodésique), triées par distance croissante."""
    ranked = sorted(
        (
            ReferenceDistance(station=s, distance_km=distance_km(lat, lon, s.latitude, s.longitude))
            for s in stations
        ),
        key=lambda rd: rd.distance_km,
    )
    return ranked[:limit]
