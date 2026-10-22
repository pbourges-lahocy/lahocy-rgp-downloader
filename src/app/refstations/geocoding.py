"""Géocodage d'adresses via le service IGN Géoplateforme (données BAN).

Endpoint vérifié en réel : `GET https://data.geopf.fr/geocodage/search?q=...&limit=N`
renvoie une FeatureCollection GeoJSON (coordonnées [lon, lat] WGS84, score de
pertinence, libellé complet). L'URL vient de `config.yaml`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode

from app.utils.http_client import RgpHttpClient


class GeocodingError(RuntimeError):
    """Réponse du géocodeur illisible."""


@dataclass(frozen=True)
class GeocodeResult:
    label: str
    latitude: float
    longitude: float
    score: float


def parse_geocode_response(data: dict) -> list[GeocodeResult]:
    results: list[GeocodeResult] = []
    for feature in data.get("features", []):
        try:
            lon, lat = feature["geometry"]["coordinates"][:2]
            props = feature.get("properties", {})
            results.append(
                GeocodeResult(
                    label=str(props.get("label") or props.get("name") or "Adresse sans libellé"),
                    latitude=float(lat),
                    longitude=float(lon),
                    score=float(props.get("score", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # entrée malformée : on garde les autres résultats
    return results


def geocode(client: RgpHttpClient, url: str, query: str, limit: int) -> list[GeocodeResult]:
    query = query.strip()
    if not query:
        raise ValueError("Saisissez une adresse à rechercher.")
    text = client.get_text(f"{url}?{urlencode({'q': query, 'limit': limit})}")
    try:
        return parse_geocode_response(json.loads(text))
    except json.JSONDecodeError as exc:
        raise GeocodingError(f"Réponse du géocodeur illisible : {exc}") from exc
