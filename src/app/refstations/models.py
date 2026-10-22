"""Modèle commun d'une antenne de référence, quel que soit le réseau d'origine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceStation:
    source_id: str  # identifiant du réseau/caster : "rgp", "centipede"...
    code: str  # code 4 lettres RGP, ou mountpoint NTRIP
    name: str
    latitude: float
    longitude: float
    country: str = ""
    network: str = ""
    constellations: str = ""

    @property
    def key(self) -> str:
        return f"{self.source_id}:{self.code}"


@dataclass(frozen=True)
class ReferenceDistance:
    station: ReferenceStation
    distance_km: float
