#!/usr/bin/env python3
"""
GPS Viewer — Application desktop
PyQt5 · matplotlib · contextily · OpenStreetMap

Usage :
    python3 gps_viewer.py [fichier.txt]
"""

import sys
import os
import math
import glob
import shutil
import json
import traceback
from pathlib import Path

import contextily as cx

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel,
    QFileDialog, QStatusBar, QMessageBox,
    QFrame, QSizePolicy, QProgressBar,
    QDialog, QDialogButtonBox, QSplashScreen,
    QPushButton, QPlainTextEdit,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QPainter, QColor, QPen

from gps_nmea import GPSData, load_points, to_webmerc, speed_kmh_between
from map_canvas import (MapCanvas, _TRACK_PALETTE, _TILE_CACHE_DIR,
                         _cache_size_mb, _retire_thread)
from chart_canvas import ChartCanvas, C_ALT, C_SPD
from stats_panel import StatsPanel
from dialogs import (CoordDialog, ParcoursPropDialog,
                     SettingsDialog, LoraConnectDialog)
from lora_thread import LoraThread, default_lora_output_path
from lora_monitor import LoraMonitorWindow
from view_3d import View3DWindow
from app_menus import MenusMixin
from app_annotations import AnnotationsMixin
from app_config import (PersistenceMixin, _CONFIG_DIR, _RECENT_FILE,
                         _LAST_TRACK_FILE, _SETTINGS_FILE, _LAYOUT_FILE,
                         _MAX_RECENT, _TRACKS_DIR, _TRACKS_JSON)


def _to_portable_path(path: str) -> str:
    """Convertit un chemin absolu en chemin relatif au répertoire utilisateur
    (préfixe '~'), pour que le fichier de trace reste valide si le projet
    est déplacé ou ouvert sous un autre compte."""
    try:
        rel = os.path.relpath(os.path.abspath(path), str(Path.home()))
    except ValueError:
        # Chemin sur un autre disque que le home (Windows) : inchangé
        return path
    if rel.startswith('..'):
        # En dehors du répertoire utilisateur : conserver le chemin absolu
        return path
    return '~/' + rel.replace(os.sep, '/')


def _from_portable_path(path: str) -> str:
    """Résout un chemin stocké dans un fichier de trace ('~/...' ou absolu)."""
    return os.path.expanduser(path)


def _extract_time_strs(gps) -> list:
    """Retourne une liste de chaînes 'HH:MM' (une par point GPS)."""
    result = []
    for p in gps.points:
        t = p.get('time', '')
        parts = t.replace(' UTC', '').split(':')
        result.append(f'{parts[0]}:{parts[1]}' if len(parts) >= 2 else '')
    return result


# ══════════════════════════════════════════════════════════════════════
#  Fenêtre principale
# ══════════════════════════════════════════════════════════════════════

class MainWindow(MenusMixin, AnnotationsMixin, PersistenceMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('GPS Viewer')
        self.resize(1380, 840)
        self._gps: GPSData | None = None
        self._gps_list: list      = []
        self._view3d: 'View3DWindow | None' = None
        self._startup_photos_shown = False
        self._parcours_titre: str = ''
        self._parcours_description: str = ''
        # ── Paramètres par défaut (écrasés par _load_settings) ──
        self._pref_track_linewidth: float = 2.5
        self._pref_map_alpha:       float = 1.0
        self._pref_photo_zoom:      float = 0.8
        self._pref_photo_cross:     int   = 16
        self._pref_cursor_dot:      int   = 12
        self._pref_autopan_margin:  int   = 0
        self._pref_remember_layout: bool  = False
        self._current_track_path: Path = self._resolve_startup_track()
        # ── État réception LoRa live ─────────────────────────────────
        self._lora_thread:      'LoraThread | None' = None
        self._lora_raw_points:  list                = []
        self._lora_output_path: 'Path | None'       = None
        self._lora_monitor: 'LoraMonitorWindow | None' = None
        self._load_settings()
        self._build_ui()
        self._apply_settings_to_map()
        self._build_menus()
        # Timer de mise à jour des graphiques pendant la réception live (3 s)
        self._lora_chart_timer = QTimer(self, interval=3000, singleShot=False)
        self._lora_chart_timer.timeout.connect(self._update_lora_charts)
        self.setAcceptDrops(True)
        self._load_track_json()
        if self._pref_remember_layout:
            self._restore_layout()

    # ── Interface ────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_toolbar()

        # Canvases
        self._map       = MapCanvas()
        self._chart_alt = ChartCanvas('Profil altimétrique', C_ALT, self._on_hover, self._on_chart_click)
        self._chart_spd = ChartCanvas('Vitesse (km/h)',       C_SPD, self._on_hover, self._on_chart_click)
        self._stats     = StatsPanel()

        # Splitter graphiques (horizontal, en bas)
        self._charts_split = QSplitter(Qt.Horizontal)
        self._charts_split.addWidget(self._chart_alt)
        self._charts_split.addWidget(self._chart_spd)
        self._charts_split.setSizes([680, 680])
        self._charts_split.setMinimumHeight(160)

        # Splitter principal (vertical : carte | graphiques | log LoRa)
        self._vsplit = QSplitter(Qt.Vertical)
        self._vsplit.addWidget(self._map)
        self._vsplit.addWidget(self._charts_split)
        self._vsplit.setHandleWidth(4)
        self._vsplit.setStyleSheet(
            'QSplitter::handle { background: #ddd; }')

        # ── Panneau de log LoRa (masqué par défaut) ──────────────────
        self._lora_log_panel = self._build_lora_log_panel()
        self._vsplit.addWidget(self._lora_log_panel)
        self._lora_log_panel.setVisible(False)

        # Layout central : vsplit + stats
        center = QWidget()
        h = QHBoxLayout(center)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._vsplit, stretch=1)
        h.addWidget(self._stats)
        self.setCentralWidget(center)

        # Status bar + barre de progression tuiles
        self._sb = QStatusBar()
        self._sb.setStyleSheet('font-size:11px; color:#555;')
        self.setStatusBar(self._sb)

        self._tile_progress = QProgressBar()
        self._tile_progress.setRange(0, 0)          # indéterminé = pulsation
        self._tile_progress.setFixedWidth(140)
        self._tile_progress.setFixedHeight(14)
        self._tile_progress.setTextVisible(False)
        self._tile_progress.setVisible(False)
        self._tile_progress.setStyleSheet(
            'QProgressBar { border:1px solid #ccc; border-radius:3px; background:#eee; }'
            'QProgressBar::chunk { background:#1a6fbf; border-radius:3px; }')
        self._sb.addPermanentWidget(self._tile_progress)

        size_mb = _cache_size_mb()
        cache_msg = f'{size_mb:.1f} Mo en cache' if size_mb >= 0.01 else 'cache vide'
        self._sb.showMessage(f'Prêt — Ouvrir un fichier GPS pour commencer  •  {cache_msg}')

        # Connexions canvas → widgets (après création de _map et _sb)
        self._map.tile_loading.connect(self._on_tile_loading)
        self._map.measure_updated.connect(self._sb.showMessage)
        self._map.measure_mode_cancelled.connect(
            lambda: self._act_meas.setChecked(False))
        self._act_meas.toggled.connect(self._map.set_measure_mode)
        self._map.photo_requested.connect(self._on_photo_requested)
        self._map.photo_mode_changed.connect(self._act_photo.setChecked)
        self._map.photo_clicked.connect(self._on_photo_clicked)
        self._map.photo_eye_changed.connect(
            lambda _: self._save_track_json())
        self._act_photo.toggled.connect(self._on_photo_mode_toggled)
        self._map.note_requested.connect(self._on_note_requested)
        self._map.note_mode_changed.connect(self._act_note.setChecked)
        self._map.note_clicked.connect(self._on_note_clicked)
        self._act_note.toggled.connect(self._on_note_mode_toggled)
        self._map.playback_index_changed.connect(self._on_hover)
        self._act_follow.toggled.connect(self._map.set_live_follow)
        self._map.live_follow_changed.connect(self._act_follow.setChecked)

    def _build_lora_log_panel(self) -> QWidget:
        """Construit le panneau de log LoRa (affiché uniquement en mode live)."""
        panel = QWidget()
        panel.setMinimumHeight(90)
        panel.setMaximumHeight(200)
        panel.setStyleSheet('QWidget { background:#131d2a; border-top:1px solid #2c3e55; }')

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(3)

        # ── En-tête ──────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(6)

        dot = QLabel('⬤')
        dot.setStyleSheet('color:#e67e22; font-size:10px;')
        header.addWidget(dot)

        lbl = QLabel('Log LoRa Live')
        lbl.setStyleSheet('color:#9ab; font-size:11px; font-weight:bold;')
        header.addWidget(lbl)

        self._lora_log_count_lbl = QLabel('— aucun point reçu')
        self._lora_log_count_lbl.setStyleSheet('color:#5a7a9a; font-size:10px;')
        header.addWidget(self._lora_log_count_lbl)

        header.addStretch()

        btn_clear = QPushButton('Vider')
        btn_clear.setFixedSize(52, 20)
        btn_clear.setStyleSheet(
            'QPushButton { background:#2c3e55; color:#9ab; border:none;'
            ' border-radius:3px; font-size:10px; }'
            'QPushButton:hover { background:#3d5a80; }')
        btn_clear.clicked.connect(self._lora_log_clear)
        header.addWidget(btn_clear)

        layout.addLayout(header)

        # ── Zone de texte ─────────────────────────────────────────────
        self._lora_log = QPlainTextEdit()
        self._lora_log.setReadOnly(True)
        self._lora_log.setMaximumBlockCount(500)   # conserve les 500 dernières lignes
        self._lora_log.setStyleSheet(
            'QPlainTextEdit {'
            '  background:#0e1520; color:#7fbfff;'
            '  font-family: "Courier New", monospace; font-size:11px;'
            '  border:none; selection-background-color:#1a4a80;'
            '}')
        layout.addWidget(self._lora_log)

        return panel

    def _lora_log_clear(self):
        self._lora_log.clear()

    def showEvent(self, event):
        super().showEvent(event)
        # Répartition initiale : 62 % carte / 38 % graphiques
        total = self._vsplit.height()
        self._vsplit.setSizes([int(total * 0.62), int(total * 0.38)])
        if not self._startup_photos_shown:
            self._startup_photos_shown = True
            if self._map._photo_data:
                if self._gps is None:
                    self._map.center_on_photos()
                else:
                    self._map.reload_photo_annotations()

    # ── Drag & drop ──────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.suffix.lower() == '.json':
            self._apply_track_json(path)
        else:
            self._load(str(path))

    # ── Chargement ───────────────────────────────────────────────────

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Ouvrir un fichier GPS NMEA', os.getcwd(),
            'Fichiers GPS (*.txt *.nmea *.log);;Tous les fichiers (*)')
        if path:
            self._load(path)

    def _load(self, filepath: str):
        if not os.path.exists(filepath):
            QMessageBox.critical(self, 'Erreur',
                                 f'Fichier introuvable :\n{filepath}')
            return

        self._sb.showMessage(f'Lecture de {os.path.basename(filepath)} …')
        QApplication.processEvents()

        try:
            points = load_points(filepath)
        except Exception as exc:
            QMessageBox.critical(self, 'Erreur de lecture',
                                 f'Impossible de lire le fichier :\n{exc}')
            self._sb.showMessage('Erreur')
            return

        if not points:
            QMessageBox.warning(self, 'Aucune donnée',
                'Aucune position GPS valide trouvée.\n'
                '(Toutes les trames GPGGA ont fix_quality = 0)')
            self._sb.showMessage('Aucune donnée GPS valide')
            return

        gps = GPSData(points, filepath)
        self._gps = gps

        if not self._gps_list:
            # Première trace : réinitialise la carte
            self._map.load(gps)
        else:
            # Trace supplémentaire : ajoute sans réinitialiser
            color = _TRACK_PALETTE[len(self._gps_list) % len(_TRACK_PALETTE)]
            self._map.add_track(gps, color)

        self._gps_list.append(gps)

        # Graphiques et stats sur la dernière trace ajoutée
        _alt_info = (f'D+ {gps.elev_gain:.0f} m  •  D− {gps.elev_loss:.0f} m'
                     if gps.elev_gain is not None else '')
        _time_strs = _extract_time_strs(gps)
        self._chart_alt.load(gps.distances, gps.alts,   'Altitude (m)', info=_alt_info,
                             elapsed=gps.elapsed_times, time_strs=_time_strs)
        self._chart_spd.load(gps.distances, gps.speeds, 'Vitesse (km/h)',
                             elapsed=gps.elapsed_times, time_strs=_time_strs)
        self._stats.refresh(gps)

        # Met à jour le sélecteur de trace
        self._refresh_track_combo(len(self._gps_list) - 1)

        self._update_track_title()
        n_traces = len(self._gps_list)
        self._lbl_tb.setText(
            f'<b>{gps.filename}</b>'
            f' &nbsp;|&nbsp; {gps.count:,} points'
            f' &nbsp;|&nbsp; {gps.total_dist:.0f} m'
            + (f' &nbsp;|&nbsp; Alt {gps.alt_min:.0f}–'
               f'{gps.alt_max:.0f} m'
               if gps.alt_min is not None else '')
            + (f' &nbsp;|&nbsp; D+ {gps.elev_gain:.0f} m'
               f' &nbsp; D− {gps.elev_loss:.0f} m'
               if gps.elev_gain is not None else '')
            + f' &nbsp;|&nbsp; Vmax {gps.spd_max:.1f} km/h'
            + (f' &nbsp;|&nbsp; <i>({n_traces} traces)</i>' if n_traces > 1 else '')
        )
        _elev = (f'  •  D+ {gps.elev_gain:.0f} m  D− {gps.elev_loss:.0f} m'
                 if gps.elev_gain is not None else '')
        self._sb.showMessage(
            f'{gps.filename} — {gps.count:,} positions valides  •  '
            f'Distance : {gps.total_dist:.1f} m'
            + _elev
            + f'  •  Vmax : {gps.spd_max:.1f} km/h'
            + (f'  •  {n_traces} traces au total' if n_traces > 1 else '')
        )

    # ── Curseur synchronisé ──────────────────────────────────────────

    def _on_hover(self, index):
        self._map.update_cursor(index)
        self._chart_alt.update_cursor(index)
        self._chart_spd.update_cursor(index)
        if self._gps:
            self._stats.update_cursor(self._gps, index)

    def _on_chart_click(self, index):
        self._map.center_on_point(index)

    # ── Sélection de la trace active pour les graphiques ─────────────

    def _refresh_track_combo(self, select_index: int | None = None):
        """Reconstruit le combo de sélection de trace et gère sa visibilité."""
        n = len(self._gps_list)
        self._track_combo.blockSignals(True)
        self._track_combo.clear()
        for gps in self._gps_list:
            self._track_combo.addItem(gps.filename)
        if n >= 2:
            self._track_combo.addItem('— Toutes les traces GPS')
        idx = (n - 1) if select_index is None else select_index
        self._track_combo.setCurrentIndex(max(0, idx))
        self._track_combo.blockSignals(False)
        self._track_sel_action.setVisible(n >= 2)
        self._track_sel_sep.setVisible(n >= 2)

    def _on_chart_track_changed(self, index: int):
        n = len(self._gps_list)
        if n == 0:
            return
        if index == n:  # "— Toutes les traces GPS"
            self._show_all_tracks_charts()
            self._map.set_track_filter(None)
            return
        if not (0 <= index < n):
            return
        self._gps = self._gps_list[index]
        self._map.set_cursor_track(self._gps)
        self._map.set_track_filter(self._gps)
        _alt_info = (f'D+ {self._gps.elev_gain:.0f} m  •  D− {self._gps.elev_loss:.0f} m'
                     if self._gps.elev_gain is not None else '')
        _time_strs = _extract_time_strs(self._gps)
        self._chart_alt.load(self._gps.distances, self._gps.alts, 'Altitude (m)', info=_alt_info,
                             elapsed=self._gps.elapsed_times, time_strs=_time_strs)
        self._chart_spd.load(self._gps.distances, self._gps.speeds, 'Vitesse (km/h)',
                             elapsed=self._gps.elapsed_times, time_strs=_time_strs)
        self._stats.refresh(self._gps)
        _elev = (f'  •  D+ {self._gps.elev_gain:.0f} m  D− {self._gps.elev_loss:.0f} m'
                 if self._gps.elev_gain is not None else '')
        self._sb.showMessage(
            f'Graphiques : {self._gps.filename}'
            f'  •  {self._gps.count:,} points'
            f'  •  {self._gps.total_dist:.0f} m'
            + _elev
            + f'  •  Vmax {self._gps.spd_max:.1f} km/h')

    def _show_all_tracks_charts(self):
        """Affiche les graphiques de toutes les traces superposées."""
        series_alt, series_spd = [], []
        for i, gps in enumerate(self._gps_list):
            color = _TRACK_PALETTE[i % len(_TRACK_PALETTE)]
            lbl_alt = (f'{gps.filename}  (D+ {gps.elev_gain:.0f} m  D− {gps.elev_loss:.0f} m)'
                       if gps.elev_gain is not None else gps.filename)
            series_alt.append((gps.distances, gps.alts,    lbl_alt,       color))
            series_spd.append((gps.distances, gps.speeds,  gps.filename,  color))
        self._chart_alt.load_multi(series_alt, 'Altitude (m)')
        self._chart_spd.load_multi(series_spd, 'Vitesse (km/h)')
        self._gps = self._gps_list[0]  # trace de référence pour le curseur carte
        self._stats.clear()
        n = len(self._gps_list)
        self._sb.showMessage(f'Graphiques : {n} traces GPS superposées')

    # ── Vue 3D ───────────────────────────────────────────────────────

    def _open_3d_view(self):
        if not self._gps_list:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Vue 3D',
                'Chargez au moins une trace GPS avant d\'ouvrir la vue 3D.')
            return
        if self._view3d is None or not self._view3d.isVisible():
            self._view3d = View3DWindow(self._gps_list, parent=self)
            self._view3d.show()
        else:
            self._view3d.refresh(self._gps_list)
            self._view3d.raise_()
            self._view3d.activateWindow()

    # ── Barre de progression tuiles ──────────────────────────────────

    def _on_tile_loading(self, started: bool):
        self._tile_progress.setVisible(started)

    # ── Coloration de trace ──────────────────────────────────────────

    def _select_track_mode(self, mode: str):
        labels = {'flat': 'Trace', 'altitude': 'Trace ▲alt', 'speed': 'Trace ⚡vit'}
        self._btn_color.setText(f'◆  {labels.get(mode, "Trace")}')
        self._map.set_track_mode(mode)

    def _on_toggle_cursor_info(self, visible: bool):
        self._map.set_show_cursor_info(visible)
        self._chart_alt.set_show_cursor_info(visible)
        self._chart_spd.set_show_cursor_info(visible)

    # ── Préférences ──────────────────────────────────────────────────
    # _load_settings() / _save_settings() : voir app_config.PersistenceMixin

    def _apply_settings_to_map(self):
        self._map.set_track_linewidth(self._pref_track_linewidth)
        self._map.set_map_alpha(self._pref_map_alpha)
        self._map.set_photo_marker_size(self._pref_photo_zoom, self._pref_photo_cross)
        self._map.set_cursor_dot_size(self._pref_cursor_dot)
        self._map.set_autopan_margin(self._pref_autopan_margin)

    def _on_pref_changed(self, key: str, value):
        if key == 'track_linewidth':
            self._pref_track_linewidth = value
            self._map.set_track_linewidth(value)
        elif key == 'map_alpha':
            self._pref_map_alpha = value
            self._map.set_map_alpha(value)
        elif key == 'photo_zoom':
            self._pref_photo_zoom = value
            self._map.set_photo_marker_size(self._pref_photo_zoom, self._pref_photo_cross)
        elif key == 'photo_cross':
            self._pref_photo_cross = value
            self._map.set_photo_marker_size(self._pref_photo_zoom, self._pref_photo_cross)
        elif key == 'cursor_dot':
            self._pref_cursor_dot = value
            self._map.set_cursor_dot_size(value)
        elif key == 'autopan_margin':
            self._pref_autopan_margin = value
            self._map.set_autopan_margin(value)
        elif key == 'remember_layout':
            self._pref_remember_layout = value

    def _on_prefs(self):
        dlg = SettingsDialog(
            self,
            track_linewidth = self._pref_track_linewidth,
            map_alpha       = self._pref_map_alpha,
            photo_zoom      = self._pref_photo_zoom,
            photo_cross     = self._pref_photo_cross,
            cursor_dot      = self._pref_cursor_dot,
            autopan_margin  = self._pref_autopan_margin,
            remember_layout = self._pref_remember_layout,
            on_changed      = self._on_pref_changed,
        )
        dlg.exec_()
        self._save_settings()

    # _save_layout() / _restore_layout() : voir app_config.PersistenceMixin

    def closeEvent(self, event):
        # Arrêt propre du thread LoRa avant fermeture (sans demander de charger)
        if self._lora_thread is not None:
            self._lora_chart_timer.stop()
            self._lora_thread.stop()
            self._lora_thread.wait(2000)
            self._lora_thread = None
        # Tuiles : annule les téléchargements en attente et coupe l'émission
        # des signaux (les threads du chargeur ne sont pas des QThread).
        self._map._tiles.shutdown()
        # Courbes SRTM : cancel() est coopératif et n'interrompt pas
        # forcément le thread avant la fermeture de la fenêtre — on le
        # retient ailleurs pour éviter le crash
        # « QThread: Destroyed while thread is still running ».
        if self._map._contour_worker is not None:
            self._map._contour_worker.cancel()
            _retire_thread(self._map._contour_worker)
        if self._view3d is not None:
            self._view3d._cancel_fetch()
        if self._pref_remember_layout:
            self._save_layout()
        event.accept()

    # ── Fichiers récents ─────────────────────────────────────────────
    # _load_recent() / _save_recent() / _add_to_recent() /
    # _refresh_recent_menu() / _clear_recent() : voir app_config.PersistenceMixin

    # ── Sources de tuiles disponibles ────────────────────────────────
    # data.geopf.fr = nouveau portail IGN open data (2023), sans clé API.
    # Remplace l'ancien wxs.ign.fr/essentiels désormais obsolète.

    _IGN_BASE = (
        'https://data.geopf.fr/wmts'
        '?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0'
        '&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}'
        '&STYLE=normal'
    )
    _TILE_SOURCES = {
        'osm': {
            'source': cx.providers.OpenStreetMap.Mapnik,
            'label':  '▦  OpenStreetMap',
            'short':  'OSM',
            # OSM bloque le User-Agent aléatoire par défaut de contextily
            # ('contextily-<uuid>'), trop utilisé par des scripts qui ne
            # respectent pas sa politique d'usage des tuiles (exige un
            # User-Agent identifiant l'application) :
            # https://operations.osmfoundation.org/policies/tiles/
            'headers': {'User-Agent': 'GPS-Viewer/1.0'},
        },
        'esri': {
            'source': cx.providers.Esri.WorldImagery,
            'label':  '⊕  Satellite (Esri)',
            'short':  'Satellite Esri',
            'headers': {},
        },
        'ign_ortho': {
            'source':  _IGN_BASE + '&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&FORMAT=image/jpeg',
            'label':  '⊕  Orthophoto IGN',
            'short':  'Orthophoto IGN',
            'headers': {'User-Agent': 'GPS-Viewer/1.0'},
        },
        'ign_plan': {
            'source':  _IGN_BASE + '&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&FORMAT=image/png',
            'label':  '⬡  Plan IGN',
            'short':  'Plan IGN',
            'headers': {'User-Agent': 'GPS-Viewer/1.0'},
        },
    }

    def _select_tiles(self, key: str):
        info = self._TILE_SOURCES[key]
        self._map.set_tile_source(info['source'], info.get('headers', {}))
        self._btn_tiles.setText(f"▦  {info['short']}")

    # ── Plein écran ───────────────────────────────────────────────────

    def _set_fullscreen(self, on: bool):
        """Plein écran : seule la carte reste affichée (F11 pour revenir)."""
        if on == self.isFullScreen():
            return
        if on:
            self._fs_saved = {
                'maximized': self.isMaximized(),
                'widgets': {w: w.isVisible() for w in (
                    self.menuBar(), self._tb, self._charts_split,
                    self._lora_log_panel, self._stats, self._sb)},
            }
            for w in self._fs_saved['widgets']:
                w.setVisible(False)
            self.showFullScreen()
        else:
            saved = getattr(self, '_fs_saved', None) or {}
            for w, visible in saved.get('widgets', {}).items():
                w.setVisible(visible)
            if saved.get('maximized'):
                self.showMaximized()
            else:
                self.showNormal()

    # ── Navigation par coordonnées ────────────────────────────────────

    def _goto_coords(self):
        dlg = CoordDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            lat, lon, zoom = dlg.coords()
            self._sb.showMessage(f'Navigation vers ({lat:.5f}°, {lon:.5f}°) …')
            QApplication.processEvents()
            self._map.goto(lat, lon, zoom)
            self._sb.showMessage(
                f'Position : {lat:.6f}° N   {lon:.6f}° E   — Zoom {zoom}')

    # ── À propos ─────────────────────────────────────────────────────

    # ── Gestion du cache de tuiles ────────────────────────────────────

    def _cache_info(self):
        size_mb   = _cache_size_mb()
        n_files   = sum(1 for f in _TILE_CACHE_DIR.rglob('*') if f.is_file())
        QMessageBox.information(self, 'Cache de tuiles',
            f'<b>Répertoire :</b><br><code>{_TILE_CACHE_DIR}</code><br><br>'
            f'<b>Taille :</b> {size_mb:.2f} Mo<br>'
            f'<b>Fichiers :</b> {n_files:,}<br><br>'
            'Les tuiles téléchargées sont réutilisées entre les sessions,<br>'
            'ce qui évite de les re-télécharger à chaque ouverture.')

    def _cache_clear(self):
        size_mb = _cache_size_mb()
        if size_mb < 0.01:
            QMessageBox.information(self, 'Cache de tuiles', 'Le cache est déjà vide.')
            return
        reply = QMessageBox.question(
            self, 'Vider le cache',
            f'Le cache occupe <b>{size_mb:.1f} Mo</b>.<br>'
            'Supprimer toutes les tuiles en cache ?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            shutil.rmtree(_TILE_CACHE_DIR, ignore_errors=True)
            _TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cx.set_cache_dir(str(_TILE_CACHE_DIR))
            self._sb.showMessage('Cache de tuiles vidé.')

    def _save_track_json(self):
        """Sauvegarde toutes les positions photo dans le fichier de trace actif."""
        self._current_track_path.parent.mkdir(parents=True, exist_ok=True)
        photos = [
            {
                'lat':         round(e['lat'], 8),
                'lon':         round(e['lon'], 8),
                'file':        _to_portable_path(e['orig_path']),
                'thumb':       _to_portable_path(e['thumb_path']),
                'titre':       e.get('titre', ''),
                'description': e.get('description', ''),
                'angle':       e.get('angle'),
            }
            for e in self._map._photo_data
        ]
        notes = [
            {
                'lat':         round(e['lat'], 8),
                'lon':         round(e['lon'], 8),
                'titre':       e.get('titre', ''),
                'description': e.get('description', ''),
            }
            for e in self._map._note_data
        ]
        data = {
            'titre':       self._parcours_titre,
            'description': self._parcours_description,
            'gps_files':   [_to_portable_path(g.filepath) for g in self._gps_list],
            'photos':      photos,
            'notes':       notes,
        }
        self._current_track_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8')
        self._persist_track_path()
        self._update_track_title()

    def _resolve_media_path(self, path_str: str) -> str | None:
        """Résout un chemin media en chemin absolu existant.

        Essaie dans l'ordre : ~/… (répertoire utilisateur), absolu,
        relatif au JSON, relatif au CWD.
        """
        if not path_str:
            return None
        p = Path(_from_portable_path(path_str))
        if p.is_absolute():
            return str(p) if p.exists() else None
        # Relatif au répertoire du fichier JSON
        p_json = self._current_track_path.parent / p
        if p_json.exists():
            return str(p_json.resolve())
        # Relatif au CWD (compatibilité anciens fichiers)
        if p.exists():
            return str(p.resolve())
        return None

    def _load_track_json(self):
        """Charge les traces GPS et les annotations photo depuis le fichier actif."""
        if not self._current_track_path.exists():
            print(f'[JSON] Fichier introuvable : {self._current_track_path}')
            self._sb.showMessage(
                f'Fichier introuvable : {self._current_track_path}')
            return
        print(f'[JSON] Ouverture de {self._current_track_path}')
        try:
            data = json.loads(self._current_track_path.read_text(encoding='utf-8'))

            self._parcours_titre       = data.get('titre', '')
            self._parcours_description = data.get('description', '')

            # Rétro-compatibilité : ancien format 'gps_file' singulier
            gps_files = data.get('gps_files') or []
            if not gps_files:
                single = data.get('gps_file')
                if single:
                    gps_files = [single]

            # Construit les entrées photo AVANT le chargement GPS
            # pour que map.load() puisse les dessiner immédiatement via _redraw_photos()
            entries = []
            for item in data.get('photos', []):
                lat, lon  = item['lat'], item['lon']
                x_m, y_m  = to_webmerc(lat, lon)
                thumb = self._resolve_media_path(item.get('thumb', ''))
                orig  = self._resolve_media_path(item.get('file', '')) \
                        or _from_portable_path(item.get('file', ''))
                if thumb:
                    entries.append({
                        'x_m':         x_m,
                        'y_m':         y_m,
                        'lat':         lat,
                        'lon':         lon,
                        'orig_path':   orig,
                        'thumb_path':  thumb,
                        'titre':       item.get('titre', ''),
                        'description': item.get('description', ''),
                        'angle':       item.get('angle'),
                    })

            # Charge les photos dans le canvas AVANT le premier map.load()
            # afin que _redraw_photos() les dessine au moment du chargement GPS
            self._map.load_photo_data(entries)

            # Charge les notes
            note_entries = []
            for item in data.get('notes', []):
                lat, lon = item['lat'], item['lon']
                x_m, y_m = to_webmerc(lat, lon)
                note_entries.append({
                    'x_m':         x_m,
                    'y_m':         y_m,
                    'lat':         lat,
                    'lon':         lon,
                    'titre':       item.get('titre', ''),
                    'description': item.get('description', ''),
                })
            self._map.load_note_data(note_entries)

            # Réinitialise la liste GPS et le sélecteur de trace
            self._gps_list = []
            self._gps      = None
            self._track_combo.blockSignals(True)
            self._track_combo.clear()
            self._track_combo.blockSignals(False)
            self._track_sel_action.setVisible(False)
            self._track_sel_sep.setVisible(False)

            missing = []
            for gps_file in gps_files:
                resolved = _from_portable_path(gps_file)
                if Path(resolved).exists():
                    print(f'[JSON]   trace GPS : {resolved}')
                    self._load(resolved)
                else:
                    print(f'[JSON]   trace GPS introuvable, ignorée : {resolved}')
                    missing.append(resolved)

            print(f'[JSON] OK — {len(gps_files)} trace(s) référencée(s), '
                  f'{len(missing)} introuvable(s), '
                  f'{len(entries)} photo(s), {len(note_entries)} note(s)')

            if missing and len(missing) == len(gps_files):
                self._sb.showMessage(
                    'Aucune trace GPS trouvée — chemins introuvables '
                    f'({len(missing)}), voir la console.')
                QMessageBox.warning(self, 'Traces GPS introuvables',
                    "Le fichier de trace ne référence aucun fichier GPS "
                    "accessible à cet emplacement (chemins absolus obsolètes "
                    "ou fichiers déplacés) :\n\n"
                    + '\n'.join(missing[:10])
                    + ('\n…' if len(missing) > 10 else ''))
            elif missing:
                self._sb.showMessage(
                    f'{len(missing)} trace(s) GPS introuvable(s), voir la console.')

        except Exception as exc:
            print(f'[JSON] Échec du chargement de {self._current_track_path} : {exc}')
            traceback.print_exc()
            self._sb.showMessage(
                f'Erreur lors du chargement du fichier JSON : {exc}')
            QMessageBox.critical(self, 'Erreur de chargement',
                'Impossible de charger le fichier de trace :\n'
                f'{self._current_track_path}\n\n{exc}')

    # ── Ouverture / enregistrement de la trace ────────────────────────
    # _resolve_startup_track() / _persist_track_path() :
    # voir app_config.PersistenceMixin

    def _apply_track_json(self, path: Path):
        """Charge un fichier JSON de trace (cœur commun pour menu et récents)."""
        self._current_track_path = path
        self._persist_track_path()
        self._add_to_recent(str(path))
        self._load_track_json()
        if self._gps is None:
            self._map.center_on_photos()
        else:
            self._map.reload_photo_annotations()
        self._update_track_title()
        n = len(self._map._photo_data)
        self._sb.showMessage(
            f'Trace ouverte : {self._current_track_path.name}'
            f'  •  {n} annotation{"s" if n > 1 else ""}')

    def _new_parcours(self):
        """Crée un nouveau parcours vide et demande où l'enregistrer."""
        path, _ = QFileDialog.getSaveFileName(
            self, 'Nouveau parcours — choisir un emplacement',
            str(self._current_track_path.parent),
            'Fichiers JSON (*.json);;Tous les fichiers (*)')
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != '.json':
            p = p.with_suffix('.json')

        # Réinitialise tout l'état
        self._gps      = None
        self._gps_list = []
        self._parcours_titre       = ''
        self._parcours_description = ''
        self._map.reset()
        self._chart_alt.clear()
        self._chart_spd.clear()
        self._stats.clear()
        self._lbl_tb.setText('Aucun fichier chargé')
        self._track_combo.blockSignals(True)
        self._track_combo.clear()
        self._track_combo.blockSignals(False)
        self._track_sel_action.setVisible(False)
        self._track_sel_sep.setVisible(False)
        self._current_track_path = p

        # Saisie optionnelle du titre et de la description
        dlg = ParcoursPropDialog('', '', self)
        if dlg.exec_() == QDialog.Accepted:
            self._parcours_titre       = dlg._titre_edit.text().strip()
            self._parcours_description = dlg._desc_edit.toPlainText().strip()

        self._save_track_json()
        self._add_to_recent(str(p))
        self._update_track_title()
        self._sb.showMessage(f'Nouveau parcours créé : {p.name}')

    def _open_track_json(self):
        """Ouvre un fichier JSON de trace (annotations photo)."""
        default_dir = str(self._current_track_path.parent)
        path, _ = QFileDialog.getOpenFileName(
            self, 'Ouvrir une trace…',
            default_dir,
            'Fichiers JSON (*.json);;Tous les fichiers (*)')
        if not path:
            return
        self._apply_track_json(Path(path))

    def _track_save(self):
        """Enregistre dans le fichier de trace actif (Ctrl+S)."""
        self._save_track_json()
        self._sb.showMessage(
            f'Trace enregistrée : {self._current_track_path.name}')

    def _track_save_as(self):
        """Enregistre sous un nouveau nom (Ctrl+Shift+S)."""
        default_dir  = str(self._current_track_path.parent)
        default_name = str(self._current_track_path)
        path, _ = QFileDialog.getSaveFileName(
            self, 'Enregistrer la trace sous…',
            default_name,
            'Fichiers JSON (*.json);;Tous les fichiers (*)')
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != '.json':
            p = p.with_suffix('.json')
        self._current_track_path = p
        self._save_track_json()
        self._add_to_recent(str(p))
        self._sb.showMessage(f'Trace enregistrée sous : {p.name}')

    def _update_track_title(self):
        """Affiche le nom du fichier JSON (et traces GPS) dans la barre de titre."""
        n = len(self._gps_list)
        if n == 0:
            gps_part = ''
        elif n == 1:
            gps_part = f' — {self._gps_list[0].filename}'
        else:
            gps_part = f' — {n} traces GPS'
        track_part = self._current_track_path.name
        if self._parcours_titre:
            self.setWindowTitle(
                f'GPS Viewer  [{track_part}]  {self._parcours_titre}{gps_part}')
        else:
            self.setWindowTitle(f'GPS Viewer  [{track_part}]{gps_part}')

    def _edit_parcours_props(self):
        """Ouvre le dialog de titre/description et sauvegarde si modifié."""
        dlg = ParcoursPropDialog(
            self._parcours_titre, self._parcours_description, self)
        if dlg.exec_() == QDialog.Accepted:
            new_titre = dlg._titre_edit.text().strip()
            new_desc  = dlg._desc_edit.toPlainText().strip()
            if new_titre != self._parcours_titre or new_desc != self._parcours_description:
                self._parcours_titre       = new_titre
                self._parcours_description = new_desc
                self._save_track_json()

    # ── Réception GPS LoRa en temps réel ─────────────────────────────

    def _on_lora_toggled(self, checked: bool):
        if checked:
            self._start_lora()
        else:
            self._stop_lora()

    def _start_lora(self):
        dlg = LoraConnectDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            # L'utilisateur a annulé : on décoche sans déclencher le slot
            self._act_lora.blockSignals(True)
            self._act_lora.setChecked(False)
            self._act_lora.blockSignals(False)
            return

        port = dlg.port()
        baud = dlg.baud()

        self._lora_raw_points  = []
        self._lora_output_path = default_lora_output_path()

        self._lora_thread = LoraThread(port, baud, self._lora_output_path)
        self._lora_thread.point_received.connect(self._on_lora_point)
        self._lora_thread.error_occurred.connect(self._on_lora_error)
        monitor = self._show_lora_monitor()
        monitor.reception_started(port, baud)
        self._lora_thread.line_received.connect(monitor.on_line)
        self._lora_thread.start()

        self._map.start_live_track()
        self._act_follow.setVisible(True)
        self._lora_chart_timer.start()

        # ── Panneau de log ─────────────────────────────────────────
        self._lora_log.clear()
        self._lora_log_count_lbl.setText('— en attente du premier point…')
        self._lora_log_panel.setVisible(True)

        # Répartit le splitter : 55 % carte / 30 % graphiques / 15 % log
        total = sum(self._vsplit.sizes()) or self._vsplit.height()
        log_h = max(110, int(total * 0.15))
        rest  = total - log_h
        self._vsplit.setSizes([int(rest * 0.62), int(rest * 0.38), log_h])

        self._lbl_lora_status.setText('⬤  LoRa Live — 0 pts')
        self._lbl_lora_status.setVisible(True)
        self._sb.showMessage(
            f'◎ Réception LoRa active — Port : {port} @ {baud} baud'
            f'  •  Fichier : {self._lora_output_path.name}')

    def _stop_lora(self, *, ask_load: bool = True):
        """Arrête la réception. Si ask_load, propose de charger le fichier sauvegardé."""
        self._lora_chart_timer.stop()

        if self._lora_thread is not None:
            self._lora_thread.stop()
            self._lora_thread.wait(2000)   # attend max 2 s (timeout série = 1 s)
            self._lora_thread = None

        self._map.stop_live_track()
        self._act_follow.setVisible(False)
        if self._lora_monitor is not None:
            self._lora_monitor.reception_stopped()

        # Masque le log et restaure le ratio carte / graphiques
        self._lora_log_panel.setVisible(False)
        sizes = self._vsplit.sizes()
        rest  = sizes[0] + sizes[1]
        if rest > 0:
            self._vsplit.setSizes([int(rest * 0.62), int(rest * 0.38), 0])

        self._lbl_lora_status.setVisible(False)
        self._act_lora.blockSignals(True)
        self._act_lora.setChecked(False)
        self._act_lora.blockSignals(False)

        n = len(self._lora_raw_points)
        if n < 2:
            self._sb.showMessage('Réception LoRa arrêtée — aucune position GPS valide reçue.')
            return

        if ask_load and self._lora_output_path and self._lora_output_path.exists():
            reply = QMessageBox.question(
                self, 'Réception LoRa terminée',
                f'<b>{n} positions GPS</b> reçues et enregistrées dans :<br>'
                f'<code>{self._lora_output_path}</code><br><br>'
                'Charger la trace sur la carte ?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self._load(str(self._lora_output_path))
        else:
            self._sb.showMessage(
                f'Réception LoRa arrêtée — {n} positions enregistrées'
                + (f' dans {self._lora_output_path.name}'
                   if self._lora_output_path else ''))

    def _on_lora_point(self, pt: dict):
        """Reçoit un point GPS valide depuis le thread LoRa (thread principal via signal Qt)."""
        x_m, y_m = to_webmerc(pt['lat'], pt['lon'])
        speed = speed_kmh_between(self._lora_raw_points[-1], pt) \
            if self._lora_raw_points else None
        self._lora_raw_points.append(pt)
        t_raw = pt.get('time', '')
        self._map.append_live_point(
            x_m, y_m, speed_kmh=speed,
            time_str=t_raw.split('.')[0] + (' UTC' if t_raw.endswith('UTC') else ''))

        n = len(self._lora_raw_points)

        # ── Entrée de log ─────────────────────────────────────────
        t_raw  = pt.get('time', '')
        # "HH:MM:SS.ss UTC" → "HH:MM:SS"
        t_str  = t_raw.replace(' UTC', '').split('.')[0] if t_raw else '—:—:—'
        alt    = pt.get('alt')
        sats   = pt.get('sats', '?')
        hdop   = pt.get('hdop')
        alt_s  = f'{alt:7.1f} m' if alt is not None else '       —'
        hdop_s = f'HDOP {hdop:.1f}' if hdop is not None else ''
        log_line = (
            f'{t_str}  '
            f'Lat {pt["lat"]:+10.6f}°  '
            f'Lon {pt["lon"]:+11.6f}°  '
            f'Alt {alt_s}  '
            f'Sats {sats:2}  {hdop_s}'
        )
        self._lora_log.appendPlainText(log_line)
        self._lora_log_count_lbl.setText(f'{n} point{"s" if n > 1 else ""} reçu{"s" if n > 1 else ""}')

        self._lbl_lora_status.setText(f'⬤  LoRa Live — {n} pts')
        if n % 10 == 0:
            self._sb.showMessage(
                f'◎ LoRa Live — {n} positions GPS'
                + (f'  •  {self._lora_output_path.name}'
                   if self._lora_output_path else ''))

    def _update_lora_charts(self):
        """Rafraîchit graphiques et statistiques avec les points live accumulés."""
        if len(self._lora_raw_points) < 2:
            return
        gps = GPSData(self._lora_raw_points,
                      str(self._lora_output_path or 'LoRa Live'))
        _time_strs = _extract_time_strs(gps)
        _alt_info  = (f'D+ {gps.elev_gain:.0f} m  •  D− {gps.elev_loss:.0f} m'
                      if gps.elev_gain is not None else '')
        self._chart_alt.load(gps.distances, gps.alts, 'Altitude (m)',
                             info=_alt_info,
                             elapsed=gps.elapsed_times, time_strs=_time_strs)
        self._chart_spd.load(gps.distances, gps.speeds, 'Vitesse (km/h)',
                             elapsed=gps.elapsed_times, time_strs=_time_strs)
        self._stats.refresh(gps)

    def _show_lora_monitor(self) -> LoraMonitorWindow:
        """Affiche (en la créant au besoin) la fenêtre des données GPS reçues."""
        if self._lora_monitor is None:
            self._lora_monitor = LoraMonitorWindow(self)
            # En haut à droite de la fenêtre principale
            geo = self.frameGeometry()
            self._lora_monitor.move(
                max(geo.left(), geo.right() - self._lora_monitor.width() - 40),
                geo.top() + 90)
        self._lora_monitor.show()
        self._lora_monitor.raise_()
        return self._lora_monitor

    def _on_lora_error(self, msg: str):
        """Erreur fatale du thread LoRa (ex : déconnexion USB)."""
        self._stop_lora(ask_load=True)
        QMessageBox.critical(self, 'Erreur de réception LoRa',
                             f'La connexion série a échoué :\n\n{msg}')

    def _about(self):
        QMessageBox.about(self, 'À propos — GPS Viewer',
            '<b>GPS Viewer</b><br>'
            'Visualisation de traces GPS NMEA<br><br>'
            '<b>Technologies :</b><br>'
            '· PyQt5 — interface graphique<br>'
            '· matplotlib — graphiques natifs<br>'
            '· contextily — tuiles OpenStreetMap<br><br>'
            '<small>Données cartographiques<br>'
            '© OpenStreetMap contributors (ODbL)</small>')


# ══════════════════════════════════════════════════════════════════════
#  Splash screen
# ══════════════════════════════════════════════════════════════════════

_LOGO_PATH = Path(__file__).parent / 'logo.png'

def _build_splash() -> QSplashScreen:
    W, H = 480, 300

    pix = QPixmap(W, H)
    pix.fill(QColor('#1a2535'))

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # ── Zone logo (96 × 96) centré en haut ──────────────────────────
    LOGO_W, LOGO_H = 96, 96
    logo_x = (W - LOGO_W) // 2
    logo_y = 28

    if _LOGO_PATH.exists():
        logo_pix = QPixmap(str(_LOGO_PATH)).scaled(
            LOGO_W, LOGO_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        offset_x = (LOGO_W - logo_pix.width())  // 2
        offset_y = (LOGO_H - logo_pix.height()) // 2
        p.drawPixmap(logo_x + offset_x, logo_y + offset_y, logo_pix)
    else:
        # Placeholder : rectangle pointillé avec nom de fichier attendu
        pen = QPen(QColor('#3d5a80'), 2, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(logo_x, logo_y, LOGO_W, LOGO_H, 10, 10)
        p.setPen(QColor('#3d5a80'))
        p.setFont(QFont('Arial', 8))
        p.drawText(logo_x, logo_y, LOGO_W, LOGO_H,
                   Qt.AlignCenter, 'logo.png')

    # ── Nom de l'application ─────────────────────────────────────────
    p.setPen(QColor('#e8edf3'))
    p.setFont(QFont('Arial', 24, QFont.Bold))
    p.drawText(0, logo_y + LOGO_H + 16, W, 38,
               Qt.AlignHCenter | Qt.AlignVCenter, 'GPS Viewer')

    # ── Sous-titre ───────────────────────────────────────────────────
    p.setPen(QColor('#7a9cbf'))
    p.setFont(QFont('Arial', 10))
    p.drawText(0, logo_y + LOGO_H + 54, W, 24,
               Qt.AlignHCenter | Qt.AlignVCenter,
               'Visualisation de traces GPS NMEA')

    # ── Séparateur ───────────────────────────────────────────────────
    sep_y = H - 36
    p.setPen(QPen(QColor('#2c3e55'), 1))
    p.drawLine(40, sep_y, W - 40, sep_y)

    # ── Crédits cartographiques ──────────────────────────────────────
    p.setPen(QColor('#3d5a80'))
    p.setFont(QFont('Arial', 8))
    p.drawText(0, sep_y + 4, W, 24,
               Qt.AlignHCenter | Qt.AlignVCenter,
               '© OpenStreetMap contributors  •  PyQt5 · matplotlib · contextily')

    p.end()

    splash = QSplashScreen(pix, Qt.WindowStaysOnTopHint)
    splash.showMessage(
        'Chargement…',
        Qt.AlignBottom | Qt.AlignHCenter,
        QColor('#7a9cbf'))
    return splash


# ══════════════════════════════════════════════════════════════════════
#  Point d'entrée
# ══════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName('GPS Viewer')
    app.setStyle('Fusion')

    # Palette légèrement adoucie
    from PyQt5.QtGui import QPalette, QColor
    pal = app.palette()
    pal.setColor(QPalette.Window,       QColor('#f5f5f5'))
    pal.setColor(QPalette.WindowText,   QColor('#222222'))
    pal.setColor(QPalette.Base,         QColor('#ffffff'))
    pal.setColor(QPalette.AlternateBase,QColor('#f0f0f0'))
    app.setPalette(pal)

    splash = _build_splash()
    splash.show()
    app.processEvents()

    win = MainWindow()
    win.show()
    splash.finish(win)

    if len(sys.argv) > 1:
        arg_path = Path(sys.argv[1])
        if arg_path.suffix.lower() == '.json':
            win._apply_track_json(arg_path)
        else:
            win._load(str(arg_path))

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
