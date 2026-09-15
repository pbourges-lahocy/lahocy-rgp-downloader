"""Calcul de distance géodésique entre deux points WGS84.

Utilise l'ellipsoïde WGS84 via pyproj.Geod plutôt qu'une formule de
Haversine approximative, puisque pyproj est déjà une dépendance du projet.
"""

from __future__ import annotations

from pyproj import Geod

_GEOD = Geod(ellps="WGS84")


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance géodésique en kilomètres entre deux points (lat, lon) WGS84."""
    _, _, distance_m = _GEOD.inv(lon1, lat1, lon2, lat2)
    return distance_m / 1000.0
