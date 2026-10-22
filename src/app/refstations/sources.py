"""Registre des réseaux d'antennes de référence disponibles dans l'onglet carte.

Chaque réseau est identifié par un `source_id` stable. Le RGP vient du catalogue déjà
construit par `app.rgp.catalog` (fiches de site IGS) ; les casters NTRIP viennent de
la configuration (`reference_networks.ntrip_casters`) : ajouter un caster NTRIP 2.0
public se fait donc dans `config.yaml`, sans toucher au code.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.loader import AppConfig
from app.refstations.models import ReferenceStation
from app.rgp.stations import Station

RGP_SOURCE_ID = "rgp"
RGP_SOURCE_NAME = "RGP (IGN)"


@dataclass(frozen=True)
class SourceInfo:
    id: str
    name: str


def available_sources(config: AppConfig) -> list[SourceInfo]:
    return [SourceInfo(RGP_SOURCE_ID, RGP_SOURCE_NAME)] + [
        SourceInfo(c.id, c.name) for c in config.reference.ntrip_casters
    ]


def rgp_reference_stations(stations: list[Station]) -> list[ReferenceStation]:
    return [
        ReferenceStation(
            source_id=RGP_SOURCE_ID,
            code=s.code.upper(),
            name=s.name,
            latitude=s.latitude,
            longitude=s.longitude,
            country=s.country,
            network="RGP",
            constellations=s.satellite_system,
        )
        for s in stations
    ]
