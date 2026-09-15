"""Conversions de coordonnées : Lambert-93 (EPSG:2154) <-> WGS84 (EPSG:4326).

Utilise pyproj pour toutes les transformations — ne jamais réimplémenter
une projection cartographique à la main.
"""

from __future__ import annotations

import re

from pyproj import Transformer

_L93_TO_WGS84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
_WGS84_TO_L93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

# Bornes approximatives de validité de la projection Lambert-93 (France métropolitaine).
L93_X_RANGE = (0, 1_400_000)
L93_Y_RANGE = (6_000_000, 7_200_000)


class InvalidCoordinatesError(ValueError):
    """Levée quand des coordonnées saisies sont hors plage plausible."""


def lambert93_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Retourne (latitude, longitude) en degrés décimaux WGS84 à partir de X/Y Lambert-93."""
    if not (L93_X_RANGE[0] <= x <= L93_X_RANGE[1] and L93_Y_RANGE[0] <= y <= L93_Y_RANGE[1]):
        raise InvalidCoordinatesError(
            f"Coordonnées Lambert-93 hors plage plausible (X={x}, Y={y})."
        )
    lon, lat = _L93_TO_WGS84.transform(x, y)
    return lat, lon


def wgs84_to_lambert93(lat: float, lon: float) -> tuple[float, float]:
    """Retourne (X, Y) Lambert-93 à partir d'une latitude/longitude WGS84 en degrés décimaux."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise InvalidCoordinatesError(f"Latitude/longitude WGS84 invalide (lat={lat}, lon={lon}).")
    x, y = _WGS84_TO_L93.transform(lon, lat)
    return x, y


_SEXAGESIMAL_RE = re.compile(r"^([+-]?)(\d+)\.?(\d*)$")


def parse_igs_sexagesimal(value: str) -> float:
    """Convertit une coordonnée au format IGS Site Log (±[D]D[D]MMSS.ss) en degrés décimaux.

    Utilisé par les fiches de site RGP (logsheet), où la latitude est encodée sur
    2 chiffres de degrés et la longitude sur 3 (voir docs/RGP_IGN.md §2.3).
    Le nombre de chiffres de degrés est déduit de la longueur de la partie entière
    plutôt que supposé fixe, ce qui gère les deux cas avec la même fonction.

    Tolère deux écarts mineurs au format observés dans des fiches réelles du RGP
    (signe '+' omis pour une valeur positive, point décimal final sans chiffre) —
    mais reste strict sur la structure globale : toute valeur qui ne ressemble
    manifestement pas à un DDMMSS (trop peu de chiffres) est rejetée plutôt que devinée.
    """
    match = _SEXAGESIMAL_RE.match(value.strip())
    if not match:
        raise ValueError(f"Format sexagésimal IGS inattendu : {value!r}")

    sign_str, int_part, frac_part = match.groups()
    frac_part = frac_part or "0"
    if len(int_part) < 4:
        raise ValueError(f"Partie entière trop courte pour DDMMSS : {value!r}")

    seconds = float(f"{int_part[-2:]}.{frac_part}")
    minutes = int(int_part[-4:-2])
    degrees = int(int_part[:-4]) if len(int_part) > 4 else 0

    decimal = degrees + minutes / 60 + seconds / 3600
    return -decimal if sign_str == "-" else decimal
