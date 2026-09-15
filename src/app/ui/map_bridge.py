"""Objet exposé à la page Leaflet via QWebChannel (événements JS -> Python)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot


class MapBridge(QObject):
    chantier_clicked = Signal(float, float)
    station_clicked = Signal(str)
    map_ready = Signal()

    @Slot(float, float)
    def notify_chantier_clicked(self, lat: float, lon: float) -> None:
        self.chantier_clicked.emit(lat, lon)

    @Slot(str)
    def notify_station_clicked(self, code: str) -> None:
        self.station_clicked.emit(code)

    @Slot()
    def notify_map_ready(self) -> None:
        self.map_ready.emit()
