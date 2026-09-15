"""Modèle de station RGP et recherche des stations les plus proches d'un chantier."""

from __future__ import annotations

from dataclasses import dataclass

from app.geo.distance import distance_km


@dataclass(frozen=True)
class Station:
    """Une station du réseau RGP, telle que décrite par sa fiche de site (logsheet)."""

    code: str  # code 4 caractères utilisé dans les noms de fichiers RINEX (ex. "aaer")
    site_id9: str  # identifiant 9 caractères IGS (ex. "AAER00FRA")
    name: str
    city: str
    country: str
    latitude: float
    longitude: float
    elevation_m: float
    satellite_system: str  # ex. "GPS+GLO+GAL+BDS+SBAS", tel que déclaré par le récepteur actif
    logsheet_filename: str


@dataclass(frozen=True)
class StationDistance:
    station: Station
    distance_km: float


def find_nearest(
    stations: list[Station], site_lat: float, site_lon: float, limit: int | None = None
) -> list[StationDistance]:
    """Classe les stations par distance croissante au chantier (site_lat, site_lon)."""
    ranked = sorted(
        (
            StationDistance(station=s, distance_km=distance_km(site_lat, site_lon, s.latitude, s.longitude))
            for s in stations
        ),
        key=lambda sd: sd.distance_km,
    )
    return ranked[:limit] if limit is not None else ranked
