"""Fenêtre principale du RGP Downloader Lahocy (Phase 4)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTime, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.config.loader import AppConfig, load_config
from app.geo.coordinates import InvalidCoordinatesError, lambert93_to_wgs84, wgs84_to_lambert93
from app.rgp.availability import AvailabilityStatus
from app.rgp.report import ChantierInfo
from app.rgp.rinex_merge import GNSS_SYSTEMS
from app.rgp.stations import Station
from app.ui.map_view import MapView
from app.ui.workers import CatalogWorker, DownloadWorker, SearchWorker, StationSearchResult
from app.utils.dates import local_range_to_utc

DEFAULT_TIMEZONE = "Europe/Paris"
_STATUS_LABELS = {
    AvailabilityStatus.DISPONIBLE: "Disponible",
    AvailabilityStatus.PARTIEL: "Partiel",
    AvailabilityStatus.INDISPONIBLE: "Indisponible",
}
_STATUS_COLORS = {
    AvailabilityStatus.DISPONIBLE: "#2e7d32",
    AvailabilityStatus.PARTIEL: "#f9a825",
    AvailabilityStatus.INDISPONIBLE: "#c62828",
}
_FAR_STATION_KM = 100.0

_COL_CHECK, _COL_CODE, _COL_NAME, _COL_DISTANCE, _COL_CADENCE, _COL_GNSS, _COL_STATUS = range(7)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Lahocy — RGP Downloader")
        self.resize(1280, 800)

        self.config: AppConfig = load_config()
        self.stations: list[Station] = []
        self.search_results: list[StationSearchResult] = []

        self._updating_location = False
        self._chantier_lat: float | None = None
        self._chantier_lon: float | None = None

        self._catalog_worker: CatalogWorker | None = None
        self._search_worker: SearchWorker | None = None
        self._download_worker: DownloadWorker | None = None

        self._build_ui()
        self._log(f"Serveur RGP configuré : {self.config.ign.base_url}")

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self._build_location_group())
        left_layout.addWidget(self._build_datetime_group())
        left_layout.addWidget(self._build_selection_group())
        left_layout.addWidget(self._build_download_group())
        left_layout.addWidget(self._build_log_group())
        left_layout.addStretch(1)

        splitter.addWidget(left_panel)

        self.map_view = MapView()
        self.map_view.chantier_clicked.connect(self._on_map_chantier_clicked)
        self.map_view.station_clicked.connect(self._on_map_station_clicked)
        splitter.addWidget(self.map_view)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 840])

        self.statusBar().showMessage("Prêt.")

    def _build_location_group(self) -> QGroupBox:
        group = QGroupBox("Localisation du chantier")
        layout = QVBoxLayout(group)
        layout.addWidget(QLabel("Cliquez sur la carte, ou saisissez des coordonnées :"))

        tabs = QTabWidget()
        layout.addWidget(tabs)

        l93_tab = QWidget()
        l93_layout = QHBoxLayout(l93_tab)
        l93_layout.addWidget(QLabel("X :"))
        self.x_l93_input = QDoubleSpinBox()
        self.x_l93_input.setRange(0, 1_400_000)
        self.x_l93_input.setDecimals(2)
        self.x_l93_input.setSuffix(" m")
        l93_layout.addWidget(self.x_l93_input)
        l93_layout.addWidget(QLabel("Y :"))
        self.y_l93_input = QDoubleSpinBox()
        self.y_l93_input.setRange(6_000_000, 7_200_000)
        self.y_l93_input.setDecimals(2)
        self.y_l93_input.setSuffix(" m")
        l93_layout.addWidget(self.y_l93_input)
        tabs.addTab(l93_tab, "Lambert-93")

        wgs84_tab = QWidget()
        wgs84_layout = QHBoxLayout(wgs84_tab)
        wgs84_layout.addWidget(QLabel("Latitude :"))
        self.lat_input = QDoubleSpinBox()
        self.lat_input.setRange(-90, 90)
        self.lat_input.setDecimals(6)
        wgs84_layout.addWidget(self.lat_input)
        wgs84_layout.addWidget(QLabel("Longitude :"))
        self.lon_input = QDoubleSpinBox()
        self.lon_input.setRange(-180, 180)
        self.lon_input.setDecimals(6)
        wgs84_layout.addWidget(self.lon_input)
        tabs.addTab(wgs84_tab, "WGS84")

        self.x_l93_input.valueChanged.connect(self._on_l93_changed)
        self.y_l93_input.valueChanged.connect(self._on_l93_changed)
        self.lat_input.valueChanged.connect(self._on_wgs84_changed)
        self.lon_input.valueChanged.connect(self._on_wgs84_changed)

        return group

    def _build_datetime_group(self) -> QGroupBox:
        group = QGroupBox("Date et horaires")
        layout = QVBoxLayout(group)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Date :"))
        self.date_input = QDateEdit()
        self.date_input.setDisplayFormat("dd/MM/yyyy")
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setMaximumDate(QDate.currentDate())
        date_row.addWidget(self.date_input)
        layout.addLayout(date_row)

        self.full_day_checkbox = QCheckBox("Journée entière")
        self.full_day_checkbox.toggled.connect(self._on_full_day_toggled)
        layout.addWidget(self.full_day_checkbox)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Début :"))
        self.start_time_input = QTimeEdit(QTime(8, 0))
        self.start_time_input.setDisplayFormat("HH:mm")
        time_row.addWidget(self.start_time_input)
        time_row.addWidget(QLabel("Fin :"))
        self.end_time_input = QTimeEdit(QTime(17, 0))
        self.end_time_input.setDisplayFormat("HH:mm")
        time_row.addWidget(self.end_time_input)
        layout.addLayout(time_row)

        return group

    def _build_selection_group(self) -> QGroupBox:
        group = QGroupBox("Stations RGP")
        layout = QVBoxLayout(group)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Nombre de stations :"))
        self.station_count_combo = QComboBox()
        self.station_count_combo.addItems(["1", "2", "3", "5", "Manuel"])
        self.station_count_combo.setCurrentText(str(self.config.selection.default_station_count))
        self.station_count_combo.currentTextChanged.connect(self._apply_default_selection)
        settings_row.addWidget(self.station_count_combo)

        settings_row.addWidget(QLabel("Cadence :"))
        self.cadence_combo = QComboBox()
        for cadence in self.config.ign.cadences:
            self.cadence_combo.addItem(f"{cadence} s", cadence)
        default_index = self.cadence_combo.findData(self.config.selection.default_cadence)
        if default_index >= 0:
            self.cadence_combo.setCurrentIndex(default_index)
        settings_row.addWidget(self.cadence_combo)
        layout.addLayout(settings_row)

        buttons_row = QHBoxLayout()
        self.search_button = QPushButton("Rechercher les stations RGP")
        self.search_button.clicked.connect(self._on_search_clicked)
        buttons_row.addWidget(self.search_button)
        self.refresh_catalog_button = QPushButton("Actualiser les stations RGP")
        self.refresh_catalog_button.clicked.connect(self._on_refresh_catalog_clicked)
        buttons_row.addWidget(self.refresh_catalog_button)
        layout.addLayout(buttons_row)

        self.search_progress = QProgressBar()
        self.search_progress.setVisible(False)
        layout.addWidget(self.search_progress)

        self.stations_table = QTableWidget(0, 7)
        self.stations_table.setHorizontalHeaderLabels(
            ["", "Station", "Nom", "Distance", "Cadence", "Constellations", "État"]
        )
        self.stations_table.horizontalHeader().setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.stations_table.verticalHeader().setVisible(False)
        self.stations_table.itemChanged.connect(self._on_table_item_changed)
        self.stations_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self.stations_table)

        return group

    def _build_download_group(self) -> QGroupBox:
        group = QGroupBox("Téléchargement")
        layout = QVBoxLayout(group)

        layout.addWidget(QLabel("Constellations à conserver :"))
        constellations_row = QHBoxLayout()
        self.constellation_checkboxes: dict[str, QCheckBox] = {}
        # Systèmes courants au RGP (voir docs/RGP_IGN.md §8) ; toutes cochées par défaut
        # = aucun filtrage (les fichiers ne sont fusionnés/réécrits que si nécessaire).
        for letter in ("G", "R", "E", "C", "S"):
            checkbox = QCheckBox(f"{GNSS_SYSTEMS[letter]} ({letter})")
            checkbox.setChecked(True)
            self.constellation_checkboxes[letter] = checkbox
            constellations_row.addWidget(checkbox)
        layout.addLayout(constellations_row)

        self.download_button = QPushButton("Télécharger les données RGP")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._on_download_clicked)
        layout.addWidget(self.download_button)

        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        self.download_progress.setRange(0, 0)
        layout.addWidget(self.download_progress)

        return group

    def _selected_constellations(self) -> set[str] | None:
        """None si tout est coché (aucun filtrage) ; sinon l'ensemble exact des lettres cochées."""
        checked = {letter for letter, box in self.constellation_checkboxes.items() if box.isChecked()}
        if checked == set(self.constellation_checkboxes):
            return None
        return checked

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Journal")
        layout = QVBoxLayout(group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        layout.addWidget(self.log_view)
        return group

    # ------------------------------------------------------------ Logging

    def _log(self, message: str, level: str = "info") -> None:
        timestamp = dt.datetime.now().strftime("%H:%M:%S")
        prefix = {"info": " ", "warn": "⚠", "error": "✗"}.get(level, " ")
        self.log_view.appendPlainText(f"[{timestamp}] {prefix} {message}")

    def _show_error(self, title: str, message: str) -> None:
        self._log(message, level="error")
        QMessageBox.critical(self, title, message)

    # ------------------------------------------------------ Localisation

    def _on_l93_changed(self) -> None:
        if self._updating_location:
            return
        try:
            lat, lon = lambert93_to_wgs84(self.x_l93_input.value(), self.y_l93_input.value())
        except InvalidCoordinatesError:
            return
        self._set_chantier(lat, lon, source="l93")

    def _on_wgs84_changed(self) -> None:
        if self._updating_location:
            return
        self._set_chantier(self.lat_input.value(), self.lon_input.value(), source="wgs84")

    def _on_map_chantier_clicked(self, lat: float, lon: float) -> None:
        self._set_chantier(lat, lon, source="map")

    def _set_chantier(self, lat: float, lon: float, source: str) -> None:
        try:
            x, y = wgs84_to_lambert93(lat, lon)
        except InvalidCoordinatesError as exc:
            self._log(str(exc), level="warn")
            return

        self._chantier_lat, self._chantier_lon = lat, lon
        self._updating_location = True
        try:
            if source != "l93":
                self.x_l93_input.setValue(x)
                self.y_l93_input.setValue(y)
            if source != "wgs84":
                self.lat_input.setValue(lat)
                self.lon_input.setValue(lon)
        finally:
            self._updating_location = False

        if source != "map":
            self.map_view.set_chantier(lat, lon)
            self.map_view.center_on(lat, lon)

    # ------------------------------------------------------------- Dates

    def _on_full_day_toggled(self, checked: bool) -> None:
        self.start_time_input.setEnabled(not checked)
        self.end_time_input.setEnabled(not checked)

    # --------------------------------------------------------- Recherche

    def _on_refresh_catalog_clicked(self) -> None:
        self._start_catalog_load(force_refresh=True)

    def _start_catalog_load(self, force_refresh: bool) -> None:
        self.search_button.setEnabled(False)
        self.refresh_catalog_button.setEnabled(False)
        self._log("Chargement du catalogue des stations RGP...")

        self._catalog_worker = CatalogWorker(self.config, force_refresh)
        self._catalog_worker.succeeded.connect(self._on_catalog_loaded)
        self._catalog_worker.failed.connect(self._on_catalog_failed)
        self._catalog_worker.start()

    def _on_catalog_loaded(self, stations: list[Station]) -> None:
        self.stations = stations
        self._log(f"{len(stations)} stations RGP connues.")
        self.search_button.setEnabled(True)
        self.refresh_catalog_button.setEnabled(True)
        self._run_search()

    def _on_catalog_failed(self, message: str) -> None:
        self.search_button.setEnabled(True)
        self.refresh_catalog_button.setEnabled(True)
        self._show_error("Catalogue RGP indisponible", f"Impossible de charger le catalogue des stations : {message}")

    def _on_search_clicked(self) -> None:
        if self._chantier_lat is None or self._chantier_lon is None:
            self._show_error("Chantier non défini", "Indiquez d'abord la position du chantier (carte ou coordonnées).")
            return
        if not self.stations:
            self._start_catalog_load(force_refresh=False)
            return
        self._run_search()

    def _run_search(self) -> None:
        try:
            site_date = self.date_input.date().toPython()
            full_day = self.full_day_checkbox.isChecked()
            start_time = None if full_day else self.start_time_input.time().toPython()
            end_time = None if full_day else self.end_time_input.time().toPython()
            start_utc, end_utc = local_range_to_utc(site_date, start_time, end_time, full_day, DEFAULT_TIMEZONE)
        except ValueError as exc:
            self._show_error("Période invalide", str(exc))
            return

        cadence = self.cadence_combo.currentData()
        limit = 10  # toujours afficher les 10 stations les plus proches (cahier des charges §5)

        self.search_button.setEnabled(False)
        self.search_progress.setVisible(True)
        self.search_progress.setRange(0, limit)
        self.search_progress.setValue(0)
        self._log(f"Recherche des stations pour le {site_date.strftime('%d/%m/%Y')}...")

        self._search_worker = SearchWorker(
            self.config, self.stations, self._chantier_lat, self._chantier_lon,
            start_utc, end_utc, full_day, cadence, limit,
        )
        self._search_worker.progress.connect(self._on_search_progress)
        self._search_worker.succeeded.connect(self._on_search_succeeded)
        self._search_worker.failed.connect(self._on_search_failed)
        self._search_worker.start()

    def _on_search_progress(self, done: int, total: int) -> None:
        self.search_progress.setValue(done)
        self.statusBar().showMessage(f"Vérification de la disponibilité... ({done}/{total})")

    def _on_search_failed(self, message: str) -> None:
        self.search_button.setEnabled(True)
        self.search_progress.setVisible(False)
        self._show_error("Recherche impossible", f"Le serveur RGP IGN est inaccessible : {message}")

    def _on_search_succeeded(self, results: list[StationSearchResult]) -> None:
        self.search_results = results
        self.search_button.setEnabled(True)
        self.search_progress.setVisible(False)
        self.statusBar().showMessage(f"{len(results)} station(s) trouvée(s).", 5000)
        self._log(f"{len(results)} station(s) analysée(s).")

        for result in results:
            for warning in result.availability.warnings:
                self._log(f"{result.station.code.upper()} : {warning}", level="warn")
            if result.distance_km > _FAR_STATION_KM:
                self._log(
                    f"{result.station.code.upper()} est particulièrement éloignée du chantier "
                    f"({result.distance_km:.1f} km).",
                    level="warn",
                )

        self._populate_table(results)
        self._apply_default_selection()
        self._update_map_stations()

    def _populate_table(self, results: list[StationSearchResult]) -> None:
        self.stations_table.blockSignals(True)
        self.stations_table.setRowCount(len(results))

        for row, result in enumerate(results):
            station = result.station
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.stations_table.setItem(row, _COL_CHECK, check_item)

            self.stations_table.setItem(row, _COL_CODE, QTableWidgetItem(station.code.upper()))
            self.stations_table.setItem(row, _COL_NAME, QTableWidgetItem(f"{station.name} ({station.city})"))
            self.stations_table.setItem(row, _COL_DISTANCE, QTableWidgetItem(f"{result.distance_km:.1f} km"))
            self.stations_table.setItem(row, _COL_CADENCE, QTableWidgetItem(f"{result.availability.requested_cadence} s"))
            self.stations_table.setItem(row, _COL_GNSS, QTableWidgetItem(station.satellite_system))

            status_item = QTableWidgetItem(_STATUS_LABELS[result.availability.status])
            status_item.setForeground(Qt.GlobalColor.white)
            status_item.setBackground(QColor(_STATUS_COLORS[result.availability.status]))
            self.stations_table.setItem(row, _COL_STATUS, status_item)

            for col in range(1, 7):
                self.stations_table.item(row, col).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        self.stations_table.blockSignals(False)

    def _apply_default_selection(self) -> None:
        if not self.search_results:
            return

        mode = self.station_count_combo.currentText()
        self.stations_table.blockSignals(True)
        try:
            if mode == "Manuel":
                for row in range(self.stations_table.rowCount()):
                    self.stations_table.item(row, _COL_CHECK).setCheckState(Qt.CheckState.Unchecked)
            else:
                target = int(mode)
                selected_so_far = 0
                for row, result in enumerate(self.search_results):
                    should_select = (
                        selected_so_far < target and result.availability.status != AvailabilityStatus.INDISPONIBLE
                    )
                    self.stations_table.item(row, _COL_CHECK).setCheckState(
                        Qt.CheckState.Checked if should_select else Qt.CheckState.Unchecked
                    )
                    if should_select:
                        selected_so_far += 1
        finally:
            self.stations_table.blockSignals(False)

        self._update_map_stations()
        self._update_download_button_state()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == _COL_CHECK:
            self._update_map_stations()
            self._update_download_button_state()

    def _on_table_selection_changed(self) -> None:
        rows = {index.row() for index in self.stations_table.selectedIndexes()}
        if len(rows) == 1:
            row = next(iter(rows))
            result = self.search_results[row]
            self.map_view.center_on(result.station.latitude, result.station.longitude, zoom=13)

    def _on_map_station_clicked(self, code: str) -> None:
        for row, result in enumerate(self.search_results):
            if result.station.code == code:
                self.stations_table.selectRow(row)
                break

    def _selected_results(self) -> list[StationSearchResult]:
        selected = []
        for row, result in enumerate(self.search_results):
            item = self.stations_table.item(row, _COL_CHECK)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(result)
        return selected

    def _update_map_stations(self) -> None:
        selected_codes = {r.station.code for r in self._selected_results()}
        payload = [
            {
                "code": r.station.code,
                "name": r.station.name,
                "lat": r.station.latitude,
                "lon": r.station.longitude,
                "distance_km": r.distance_km,
                "status": r.availability.status.value,
                "selected": r.station.code in selected_codes,
            }
            for r in self.search_results
        ]
        self.map_view.set_stations(payload)

    def _update_download_button_state(self) -> None:
        self.download_button.setEnabled(bool(self._selected_results()))

    # ------------------------------------------------------- Téléchargement

    def _on_download_clicked(self) -> None:
        selected = self._selected_results()
        if not selected:
            self._show_error("Aucune station sélectionnée", "Sélectionnez au moins une station avant de télécharger.")
            return

        destination = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination")
        if not destination:
            return
        destination_path = Path(destination)

        try:
            x_l93, y_l93 = wgs84_to_lambert93(self._chantier_lat, self._chantier_lon)
        except InvalidCoordinatesError:
            x_l93, y_l93 = 0.0, 0.0

        site_date = self.date_input.date().toPython()
        full_day = self.full_day_checkbox.isChecked()
        period_label = (
            "journée entière"
            if full_day
            else f"{self.start_time_input.time().toString('HH:mm')} -> {self.end_time_input.time().toString('HH:mm')}"
        )
        chantier = ChantierInfo(
            x_l93=x_l93, y_l93=y_l93, lat=self._chantier_lat, lon=self._chantier_lon,
            site_date=site_date, period_label=period_label,
        )

        keep_systems = self._selected_constellations()
        if keep_systems is not None and not keep_systems:
            self._show_error(
                "Aucune constellation sélectionnée", "Cochez au moins une constellation à conserver."
            )
            return

        self.download_button.setEnabled(False)
        self.download_progress.setVisible(True)
        self._log(f"Téléchargement vers {destination_path} pour {len(selected)} station(s)...")
        if keep_systems:
            self._log(f"Filtrage constellations : {', '.join(sorted(keep_systems))}")

        self._download_worker = DownloadWorker(
            self.config, chantier, destination_path, site_date, selected, keep_systems
        )
        self._download_worker.progress.connect(lambda msg: self._log(msg))
        self._download_worker.file_done.connect(self._on_download_file_done)
        self._download_worker.succeeded.connect(self._on_download_succeeded)
        self._download_worker.failed.connect(self._on_download_failed)
        self._download_worker.start()

    def _on_download_file_done(self, event) -> None:
        if event.ok:
            self._log(f"{event.station_code} : {event.filename}")
        else:
            self._log(f"{event.station_code} : {event.filename} — {event.error}", level="error")

    def _on_download_succeeded(self, report_path: str) -> None:
        self.download_progress.setVisible(False)
        self._update_download_button_state()
        self._log(f"Rapport écrit : {report_path}")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Téléchargement terminé")
        box.setText(f"Téléchargement terminé.\nRapport : {report_path}")
        open_button = box.addButton("Ouvrir le dossier", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(report_path).parent)))

    def _on_download_failed(self, message: str) -> None:
        self.download_progress.setVisible(False)
        self._update_download_button_state()
        self._show_error("Échec du téléchargement", message)
