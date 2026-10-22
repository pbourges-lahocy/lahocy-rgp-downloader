"""Onglet « Stations de référence » : carte des antennes RGP + casters NTRIP (Centipède...).

Permet de choisir les réseaux affichés, de donner une adresse (ou de cliquer sur la
carte) et de lister les antennes les plus proches, tous réseaux sélectionnés confondus.
"""

from __future__ import annotations

import datetime as dt
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.loader import AppConfig
from app.geo.coordinates import InvalidCoordinatesError, wgs84_to_lambert93
from app.refstations.geocoding import GeocodeResult
from app.refstations.models import ReferenceStation
from app.refstations.nearest import nearest_reference_stations
from app.refstations.sources import available_sources
from app.ui.map_view import MapView
from app.ui.workers import GeocodeWorker, ReferenceLoadWorker

_PALETTE = ["#1565c0", "#ef6c00", "#6a1b9a", "#2e7d32", "#00838f", "#ad1457"]
_COLUMNS = ["Réseau", "Code", "Nom", "Distance", "Pays", "Constellations"]


class ReferenceStationsTab(QWidget):
    use_position_requested = Signal(float, float)

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._sources = available_sources(config)
        self._colors = {s.id: _PALETTE[i % len(_PALETTE)] for i, s in enumerate(self._sources)}
        self._names = {s.id: s.name for s in self._sources}
        self._data: dict[str, list[ReferenceStation]] = {}
        self._position: tuple[float, float] | None = None
        self._geocode_results: list[GeocodeResult] = []
        self._shown_rows: list[ReferenceStation] = []
        self._started = False
        self._load_workers: dict[str, ReferenceLoadWorker] = {}
        self._geocode_worker: GeocodeWorker | None = None

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        left = QWidget()
        layout = QVBoxLayout(left)
        layout.addWidget(self._build_networks_group())
        layout.addWidget(self._build_position_group())
        layout.addWidget(self._build_results_group(), stretch=1)
        layout.addWidget(self._build_log_group())
        splitter.addWidget(left)

        self.map_view = MapView()
        self.map_view.set_position_label("Position recherchée")
        self.map_view.chantier_clicked.connect(self._on_map_clicked)
        self.map_view.station_clicked.connect(self._on_map_station_clicked)
        splitter.addWidget(self.map_view)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 760])

    def _build_networks_group(self) -> QGroupBox:
        group = QGroupBox("Réseaux affichés")
        layout = QVBoxLayout(group)
        self.source_checkboxes: dict[str, QCheckBox] = {}
        for source in self._sources:
            box = QCheckBox(f"● {source.name}")
            box.setChecked(True)
            box.setStyleSheet(f"QCheckBox {{ color: {self._colors[source.id]}; font-weight: bold; }}")
            box.toggled.connect(self._on_sources_changed)
            self.source_checkboxes[source.id] = box
            layout.addWidget(box)
        self.refresh_button = QPushButton("Actualiser les listes d'antennes")
        self.refresh_button.clicked.connect(lambda: self._start_load(self._checked_source_ids(), force=True))
        layout.addWidget(self.refresh_button)
        return group

    def _build_position_group(self) -> QGroupBox:
        group = QGroupBox("Position")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Adresse, commune... (ou cliquez sur la carte)")
        self.address_input.returnPressed.connect(self._on_search_clicked)
        row.addWidget(self.address_input)
        self.search_button = QPushButton("Rechercher")
        self.search_button.clicked.connect(self._on_search_clicked)
        row.addWidget(self.search_button)
        layout.addLayout(row)

        self.address_combo = QComboBox()
        self.address_combo.setVisible(False)
        self.address_combo.activated.connect(self._on_address_chosen)
        layout.addWidget(self.address_combo)

        self.position_label = QLabel("Aucune position définie.")
        self.position_label.setWordWrap(True)
        layout.addWidget(self.position_label)
        return group

    def _build_results_group(self) -> QGroupBox:
        group = QGroupBox("Antennes les plus proches")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre d'antennes :"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 50)
        self.count_spin.setValue(self._config.reference.nearest_count)
        self.count_spin.valueChanged.connect(lambda _v: self._refresh_view())
        row.addWidget(self.count_spin)
        row.addStretch(1)
        layout.addLayout(row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        header = self.table.horizontalHeader()
        for col in range(len(_COLUMNS)):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch if col == 2 else QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table)

        self.use_position_button = QPushButton("Utiliser cette position pour le téléchargement RGP")
        self.use_position_button.setEnabled(False)
        self.use_position_button.clicked.connect(self._on_use_position)
        layout.addWidget(self.use_position_button)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Journal")
        layout = QVBoxLayout(group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(200)
        self.log_view.setMaximumHeight(110)
        layout.addWidget(self.log_view)
        return group

    def _log(self, message: str, level: str = "info") -> None:
        prefix = {"info": " ", "warn": "⚠", "error": "✗"}.get(level, " ")
        self.log_view.appendPlainText(f"[{dt.datetime.now():%H:%M:%S}] {prefix} {message}")

    # ----------------------------------------------------------- Chargement

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._start_load(self._checked_source_ids(), force=False)

    def _checked_source_ids(self) -> list[str]:
        return [sid for sid, box in self.source_checkboxes.items() if box.isChecked()]

    def _on_sources_changed(self) -> None:
        missing = [sid for sid in self._checked_source_ids() if sid not in self._data]
        if missing:
            self._start_load(missing, force=False)
        else:
            self._refresh_view()

    def _start_load(self, source_ids: list[str], force: bool) -> None:
        for source_id in source_ids:
            if source_id in self._load_workers:
                continue  # déjà en cours
            hint = " (si le cache a expiré : jusqu'à 2 minutes)" if source_id == "rgp" else ""
            self._log(f"{self._names[source_id]} : chargement des antennes{hint}...")
            worker = ReferenceLoadWorker(self._config, source_id, force)
            worker.loaded.connect(self._on_source_loaded)
            worker.failed.connect(self._on_source_failed)
            worker.finished.connect(lambda sid=source_id: self._on_worker_finished(sid))
            self._load_workers[source_id] = worker
            self.refresh_button.setEnabled(False)
            worker.start()

    def _on_worker_finished(self, source_id: str) -> None:
        self._load_workers.pop(source_id, None)
        self.refresh_button.setEnabled(not self._load_workers)

    def _on_source_loaded(self, source_id: str, stations: list, warnings: list) -> None:
        self._data[source_id] = stations
        self._log(f"{self._names[source_id]} : {len(stations)} antennes.")
        for warning in warnings:
            self._log(warning, level="warn")
        self._refresh_view(fit_map=self._position is not None)

    def _on_source_failed(self, source_id: str, message: str) -> None:
        self._log(f"{self._names[source_id]} : chargement impossible — {message}", level="error")

    # ------------------------------------------------------------- Position

    def _on_search_clicked(self) -> None:
        query = self.address_input.text().strip()
        if not query:
            self._log("Saisissez une adresse à rechercher.", level="warn")
            return
        self.search_button.setEnabled(False)
        self._geocode_worker = GeocodeWorker(self._config, query)
        self._geocode_worker.succeeded.connect(self._on_geocoded)
        self._geocode_worker.failed.connect(self._on_geocode_failed)
        self._geocode_worker.start()

    def _on_geocode_failed(self, message: str) -> None:
        self.search_button.setEnabled(True)
        self._log(message, level="error")

    def _on_geocoded(self, results: list[GeocodeResult]) -> None:
        self.search_button.setEnabled(True)
        self._geocode_results = results
        if not results:
            self.address_combo.setVisible(False)
            self._log(f"Aucune adresse trouvée pour « {self.address_input.text().strip()} ».", level="warn")
            return
        self.address_combo.clear()
        self.address_combo.addItems([r.label for r in results])
        self.address_combo.setVisible(len(results) > 1)
        self._on_address_chosen(0)

    def _on_address_chosen(self, index: int) -> None:
        if 0 <= index < len(self._geocode_results):
            r = self._geocode_results[index]
            self._set_position(r.latitude, r.longitude, r.label, fit=True)

    def _on_map_clicked(self, lat: float, lon: float) -> None:
        self._set_position(lat, lon, "Point choisi sur la carte", fit=False)

    def _set_position(self, lat: float, lon: float, label: str, fit: bool) -> None:
        self._position = (lat, lon)
        text = f"{label}\nWGS84 : {lat:.6f}, {lon:.6f}"
        try:
            x, y = wgs84_to_lambert93(lat, lon)
            text += f" — Lambert-93 : X {x:.1f} / Y {y:.1f}"
        except InvalidCoordinatesError:
            pass  # hors emprise Lambert-93 : on n'affiche que le WGS84
        self.position_label.setText(text)
        self.use_position_button.setEnabled(True)
        self.map_view.set_chantier(lat, lon)
        self._refresh_view(fit_map=fit)

    def _on_use_position(self) -> None:
        if self._position is not None:
            self.use_position_requested.emit(*self._position)

    # --------------------------------------------------------- Affichage

    def _visible_stations(self) -> list[ReferenceStation]:
        return [s for sid in self._checked_source_ids() for s in self._data.get(sid, [])]

    def _popup(self, station: ReferenceStation, distance_km: float | None) -> str:
        parts = [
            f"<b>{html.escape(station.code)}</b>" + (f" — {html.escape(station.name)}" if station.name else ""),
            f"{html.escape(self._names.get(station.source_id, station.source_id))}"
            + (f" · {html.escape(station.network)}" if station.network and station.network != "RGP" else "")
            + (f" · {html.escape(station.country)}" if station.country else ""),
        ]
        if station.constellations:
            parts.append(html.escape(station.constellations))
        if distance_km is not None:
            parts.append(f"Distance : {distance_km:.1f} km")
        return "<br>".join(parts)

    def _refresh_view(self, fit_map: bool = False) -> None:
        stations = self._visible_stations()
        nearest = (
            nearest_reference_stations(stations, *self._position, self.count_spin.value())
            if self._position is not None and stations
            else []
        )
        nearest_keys = {rd.station.key: rd.distance_km for rd in nearest}

        markers = [
            {
                "id": s.key, "lat": s.latitude, "lon": s.longitude, "color": self._colors[s.source_id],
                "popup": self._popup(s, nearest_keys.get(s.key)), "highlight": s.key in nearest_keys,
            }
            for s in stations
        ]
        markers.sort(key=lambda m: m["highlight"])  # les antennes mises en avant sont dessinées au-dessus
        self.map_view.set_reference_markers(markers)

        self._shown_rows = [rd.station for rd in nearest]
        self.table.blockSignals(True)
        self.table.setRowCount(len(nearest))
        for row, rd in enumerate(nearest):
            s = rd.station
            cells = [self._names[s.source_id], s.code, s.name or "—", f"{rd.distance_km:.1f} km", s.country, s.constellations]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(QColor(self._colors[s.source_id]))
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)

        if fit_map and self._position is not None:
            points = [self._position] + [(s.latitude, s.longitude) for s in self._shown_rows]
            self.map_view.fit_to_points([list(p) for p in points])

    def _on_row_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) == 1:
            station = self._shown_rows[next(iter(rows))]
            self.map_view.center_on(station.latitude, station.longitude, zoom=13)
            self.map_view.open_reference_popup(station.key)

    def _on_map_station_clicked(self, key: str) -> None:
        for row, station in enumerate(self._shown_rows):
            if station.key == key:
                self.table.blockSignals(True)
                self.table.selectRow(row)
                self.table.blockSignals(False)
                return
