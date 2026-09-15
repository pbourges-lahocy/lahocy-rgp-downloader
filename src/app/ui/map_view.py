"""Widget carte : QWebEngineView affichant une carte Leaflet embarquée localement.

Leaflet (JS/CSS/icônes) est fourni en local dans `assets/leaflet/` — aucune dépendance
réseau pour l'affichage de la carte elle-même (seules les tuiles OpenStreetMap
nécessitent une connexion, ce que l'application requiert de toute façon pour le RGP).
"""

from __future__ import annotations

import json
from pathlib import Path

import logging

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from app.ui.map_bridge import MapBridge

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_MAP_HTML_PATH = _ASSETS_DIR / "map.html"
logger = logging.getLogger(__name__)


class _LoggingWebEnginePage(QWebEnginePage):
    """Relaie les messages console JS (erreurs de tuiles, etc.) vers le journal Python."""

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:  # noqa: N802
        logger.debug("[JS %s:%d] %s", source, line, message)


class MapView(QWebEngineView):
    chantier_clicked = Signal(float, float)
    station_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ready = False
        self._pending_calls: list[str] = []

        self.setPage(_LoggingWebEnginePage(self))

        # La page de la carte est chargée depuis file:// (assets locaux embarqués) ;
        # QtWebEngine bloque par défaut tout accès réseau distant (tuiles OSM) depuis
        # une origine locale — il faut l'autoriser explicitement.
        self.page().settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self._bridge = MapBridge()
        self._bridge.chantier_clicked.connect(self.chantier_clicked)
        self._bridge.station_clicked.connect(self.station_clicked)
        self._bridge.map_ready.connect(self._on_map_ready)

        self._channel = QWebChannel(self.page())
        self._channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(self._channel)

        self.load(QUrl.fromLocalFile(str(_MAP_HTML_PATH)))

    def _on_map_ready(self) -> None:
        self._ready = True
        for js in self._pending_calls:
            self.page().runJavaScript(js)
        self._pending_calls.clear()

    def _run_js(self, js: str) -> None:
        if self._ready:
            self.page().runJavaScript(js)
        else:
            self._pending_calls.append(js)

    def set_chantier(self, lat: float, lon: float) -> None:
        self._run_js(f"setChantier({lat!r}, {lon!r});")

    def center_on(self, lat: float, lon: float, zoom: int = 12) -> None:
        self._run_js(f"centerOn({lat!r}, {lon!r}, {zoom!r});")

    def set_stations(self, stations: list[dict]) -> None:
        self._run_js(f"setStations({json.dumps(stations)});")
