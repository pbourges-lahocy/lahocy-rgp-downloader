"""Connaissance spécifique au serveur de données RGP IGN (rgpdata.ign.fr).

Ce module est le SEUL endroit du projet qui connaît la structure réelle des
répertoires et le nommage des fichiers de l'IGN (voir docs/RGP_IGN.md). Si l'IGN
change son arborescence, son nommage ou son domaine, seul ce fichier (et
config/config.yaml) doivent être modifiés.

Ne construit et ne teste QUE des chemins RINEX 2 (nom court, répertoire `data/`)
pour l'instant : c'est le flux le plus rapidement disponible (voir docs/RGP_IGN.md
§2.1 vs §2.2). Le support RINEX 3 pourra être ajouté par des fonctions
`*_rinex3_*` supplémentaires sans toucher au reste de l'application.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.utils.dates import DAILY_SESSION_CODE, day_of_year, session_letters_for_range

# Types de fichiers RINEX 2 disponibles au RGP (voir docs/RGP_IGN.md §2.1).
OBSERVATION = "d"  # observation compressée Hatanaka (CRINEX), compressée .Z
NAV_GPS = "n"
NAV_GLONASS = "g"


@dataclass(frozen=True)
class RinexFileCandidate:
    """Un fichier RINEX 2 précis que l'on pourrait télécharger, avant vérification."""

    url: str
    filename: str
    station: str
    cadence: int
    session: str  # lettre 'a'-'x', ou DAILY_SESSION_CODE ('0')
    file_type: str  # OBSERVATION, NAV_GPS ou NAV_GLONASS

    @property
    def is_daily(self) -> bool:
        return self.session == DAILY_SESSION_CODE


class IgnProviderIGN:
    """Construit les URLs du serveur RGP IGN à partir de la configuration."""

    def __init__(self, base_url: str, data_dir: str, logsheet_dir: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._data_dir = data_dir
        self._logsheet_dir = logsheet_dir

    def logsheet_index_url(self) -> str:
        return f"{self._base_url}/{self._logsheet_dir}/"

    def logsheet_url(self, filename: str) -> str:
        return f"{self._base_url}/{self._logsheet_dir}/{filename}"

    def _day_dir_url(self, year: int, doy: int, cadence: int) -> str:
        return f"{self._base_url}/{self._data_dir}/{year:04d}/{doy:03d}/data_{cadence}"

    def rinex2_filename(
        self, station: str, doy: int, session: str, year: int, file_type: str
    ) -> str:
        yy = year % 100
        return f"{station.lower()}{doy:03d}{session}.{yy:02d}{file_type}.Z"

    def rinex2_candidate(
        self,
        station: str,
        date: dt.date,
        session: str,
        cadence: int,
        file_type: str = OBSERVATION,
    ) -> RinexFileCandidate:
        doy = day_of_year(date)
        filename = self.rinex2_filename(station, doy, session, date.year, file_type)
        url = f"{self._day_dir_url(date.year, doy, cadence)}/{filename}"
        return RinexFileCandidate(
            url=url,
            filename=filename,
            station=station.lower(),
            cadence=cadence,
            session=session,
            file_type=file_type,
        )

    def hourly_candidates_for_range(
        self,
        station: str,
        start_utc: dt.datetime,
        end_utc: dt.datetime,
        cadence: int,
        file_type: str = OBSERVATION,
    ) -> list[RinexFileCandidate]:
        """Fichiers horaires couvrant [start_utc, end_utc] (même jour UTC)."""
        letters = session_letters_for_range(start_utc, end_utc)
        return [
            self.rinex2_candidate(station, start_utc.date(), letter, cadence, file_type)
            for letter in letters
        ]

    def daily_candidate(
        self, station: str, date: dt.date, cadence: int, file_type: str = OBSERVATION
    ) -> RinexFileCandidate:
        return self.rinex2_candidate(station, date, DAILY_SESSION_CODE, cadence, file_type)
