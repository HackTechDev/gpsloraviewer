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
import datetime
from pathlib import Path

import contextily as cx

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel, QAction,
    QFileDialog, QStatusBar, QMessageBox,
    QFrame, QToolBar, QSizePolicy,
    QToolButton, QMenu, QProgressBar,
    QDialog, QDialogButtonBox, QSplashScreen, QComboBox,
)
from PyQt5.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QPainter, QColor, QPen

from gps_nmea import GPSData, load_points, to_webmerc, _webmerc_to_latlon
from map_canvas import MapCanvas, _TRACK_PALETTE, _TILE_CACHE_DIR, _cache_size_mb
from chart_canvas import ChartCanvas, C_ALT, C_SPD
from stats_panel import StatsPanel
from dialogs import CoordDialog, PhotoViewDialog, ParcoursPropDialog
from view_3d import View3DWindow

# ── Constantes application ────────────────────────────────────────────
_CONFIG_DIR       = Path.home() / '.config' / 'gps_viewer'
_RECENT_FILE      = _CONFIG_DIR / 'recent_tracks.json'
_LAST_TRACK_FILE  = _CONFIG_DIR / 'last_track.txt'
_MAX_RECENT       = 10

_TRACKS_DIR     = Path(__file__).parent / 'tracks'
_TRACKS_IMG_DIR = _TRACKS_DIR / 'images'
_TRACKS_JSON    = _TRACKS_DIR / 'track.json'


# ══════════════════════════════════════════════════════════════════════
#  Fenêtre principale
# ══════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
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
        self._current_track_path: Path = self._resolve_startup_track()
        self._build_ui()
        self._build_menus()
        self.setAcceptDrops(True)
        self._load_track_json()

    # ── Interface ────────────────────────────────────────────────────

    def _build_ui(self):
        # Toolbar
        tb = QToolBar(self)
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setStyleSheet('QToolBar { spacing: 4px; padding: 3px 6px; '
                         'background: #f0f0f0; border-bottom: 1px solid #ccc; }')
        self.addToolBar(tb)

        act_open = QAction('📂  Trace GPS', self)
        act_open.setShortcut('Ctrl+O')
        act_open.setToolTip('Ajouter une trace GPS NMEA (Ctrl+O)')
        act_open.triggered.connect(self._open_dialog)
        tb.addAction(act_open)

        act_home = QAction('⌂  Recentrer', self)
        act_home.setShortcut('Ctrl+R')
        act_home.setToolTip('Revenir à la vue initiale (Ctrl+R)')
        act_home.triggered.connect(lambda: self._map.reset_view())
        tb.addAction(act_home)

        act_goto = QAction('📍  Coordonnées', self)
        act_goto.setShortcut('Ctrl+G')
        act_goto.setToolTip('Naviguer vers des coordonnées GPS (Ctrl+G)')
        act_goto.triggered.connect(self._goto_coords)
        tb.addAction(act_goto)

        self._btn_tiles = QToolButton()
        self._btn_tiles.setText('🗺  Fond de carte')
        self._btn_tiles.setToolTip('Changer le fond de carte (Ctrl+T)')
        self._btn_tiles.setPopupMode(QToolButton.InstantPopup)
        self._btn_tiles.setShortcut('Ctrl+T')
        menu_tiles = QMenu(self._btn_tiles)
        for key, info in self._TILE_SOURCES.items():
            act = QAction(info['label'], self)
            act.triggered.connect(lambda checked=False, k=key: self._select_tiles(k))
            menu_tiles.addAction(act)
        self._btn_tiles.setMenu(menu_tiles)
        tb.addWidget(self._btn_tiles)

        # ── Coloration de trace ──────────────────────────────────────
        self._btn_color = QToolButton()
        self._btn_color.setText('🎨  Trace')
        self._btn_color.setToolTip('Coloration de la trace')
        self._btn_color.setPopupMode(QToolButton.InstantPopup)
        menu_color = QMenu(self._btn_color)
        for mode, label in [('flat', '— Couleur unie'),
                             ('altitude', '🏔  Altitude'),
                             ('speed',    '⚡  Vitesse')]:
            a = QAction(label, self)
            a.triggered.connect(lambda c=False, m=mode: self._select_track_mode(m))
            menu_color.addAction(a)
        self._btn_color.setMenu(menu_color)
        tb.addWidget(self._btn_color)

        # ── Mesure de distance ───────────────────────────────────────
        self._act_meas = QAction('📏  Mesure', self)
        self._act_meas.setCheckable(True)
        self._act_meas.setShortcut('Ctrl+D')
        self._act_meas.setToolTip(
            'Mesure de distance clic-à-clic (Ctrl+D)  •  Échap pour annuler')
        tb.addAction(self._act_meas)

        # ── Annotation photo ─────────────────────────────────────────
        self._act_photo = QAction('📷  Photo', self)
        self._act_photo.setCheckable(True)
        self._act_photo.setToolTip(
            'Annoter la carte avec une photo (P)  •  Clic pour choisir la position')
        tb.addAction(self._act_photo)

        # ── Grille / miniature ───────────────────────────────────────
        act_grid = QAction('⊞  Grille', self)
        act_grid.setCheckable(True)
        act_grid.setToolTip('Afficher la grille lat/lon (Ctrl+L)')
        act_grid.setShortcut('Ctrl+L')
        act_grid.toggled.connect(lambda v: self._map.toggle_grid(v))
        tb.addAction(act_grid)

        act_ov = QAction('🔍  Miniature', self)
        act_ov.setCheckable(True)
        act_ov.setToolTip('Afficher la miniature de localisation (Ctrl+M)')
        act_ov.setShortcut('Ctrl+M')
        act_ov.toggled.connect(lambda v: self._map.toggle_overview(v))
        tb.addAction(act_ov)

        act_contours = QAction('🏔  Courbes', self)
        act_contours.setCheckable(True)
        act_contours.setToolTip(
            'Afficher les courbes de niveau SRTM (30 m)\n'
            'Premier affichage : téléchargement des tuiles SRTM (~quelques Mo)')
        act_contours.toggled.connect(lambda v: self._map.toggle_contours(v))
        tb.addAction(act_contours)

        # ── Vue 3D ──────────────────────────────────────────────────
        act_3d = QAction('🌐  Vue 3D', self)
        act_3d.setShortcut('Ctrl+3')
        act_3d.setToolTip('Afficher la trace en 3D (altitude) (Ctrl+3)')
        act_3d.triggered.connect(self._open_3d_view)
        tb.addAction(act_3d)

        # ── Sélecteur de trace active pour les graphiques ────────────
        # Le séparateur et le widget sont gérés via leur QWidgetAction
        # (setVisible sur le QWidget lui-même est ignoré dans un QToolBar)
        _track_selector = QWidget()
        _sel_layout = QHBoxLayout(_track_selector)
        _sel_layout.setContentsMargins(4, 0, 4, 0)
        _sel_layout.setSpacing(4)
        _lbl_sel = QLabel('📊 Graphiques :')
        _lbl_sel.setStyleSheet('color:#555; font-size:12px;')
        self._track_combo = QComboBox()
        self._track_combo.setFixedWidth(180)
        self._track_combo.setToolTip(
            'Choisir la trace affichée dans les graphiques et les statistiques')
        self._track_combo.currentIndexChanged.connect(self._on_chart_track_changed)
        _sel_layout.addWidget(_lbl_sel)
        _sel_layout.addWidget(self._track_combo)
        self._track_sel_sep    = tb.addSeparator()
        self._track_sel_action = tb.addWidget(_track_selector)
        self._track_sel_sep.setVisible(False)
        self._track_sel_action.setVisible(False)

        tb.addSeparator()

        self._lbl_tb = QLabel('Aucun fichier chargé')
        self._lbl_tb.setStyleSheet('color:#555; padding: 0 8px; font-size:12px;')
        tb.addWidget(self._lbl_tb)

        # Canvases
        self._map       = MapCanvas()
        self._chart_alt = ChartCanvas('Profil altimétrique', C_ALT, self._on_hover)
        self._chart_spd = ChartCanvas('Vitesse (km/h)',       C_SPD, self._on_hover)
        self._stats     = StatsPanel()

        # Splitter graphiques (horizontal, en bas)
        charts_split = QSplitter(Qt.Horizontal)
        charts_split.addWidget(self._chart_alt)
        charts_split.addWidget(self._chart_spd)
        charts_split.setSizes([680, 680])
        charts_split.setMinimumHeight(160)

        # Splitter principal (vertical : carte | graphiques)
        self._vsplit = QSplitter(Qt.Vertical)
        self._vsplit.addWidget(self._map)
        self._vsplit.addWidget(charts_split)
        self._vsplit.setHandleWidth(4)
        self._vsplit.setStyleSheet(
            'QSplitter::handle { background: #ddd; }')

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
        self._act_photo.toggled.connect(self._map.set_photo_mode)

    def _build_menus(self):
        mb = self.menuBar()

        fm = mb.addMenu('Fichier')

        a_new = QAction('Nouveau parcours…', self)
        a_new.setShortcut('Ctrl+N')
        a_new.setToolTip('Créer un nouveau parcours vide (Ctrl+N)')
        a_new.triggered.connect(self._new_parcours)
        fm.addAction(a_new)

        fm.addSeparator()

        a_open_json = QAction('Ouvrir un parcours…', self)
        a_open_json.setToolTip('Ouvrir un fichier de trace JSON (annotations photo)')
        a_open_json.triggered.connect(self._open_track_json)
        fm.addAction(a_open_json)

        a_gps = QAction('Ajouter une trace GPS…', self)
        a_gps.setShortcut('Ctrl+O')
        a_gps.setToolTip('Charger un fichier GPS NMEA sur la carte (Ctrl+O)')
        a_gps.triggered.connect(self._open_dialog)
        fm.addAction(a_gps)

        fm.addSeparator()

        a_props = QAction('Propriétés du parcours…', self)
        a_props.setShortcut('Ctrl+I')
        a_props.setToolTip('Modifier le titre et la description de ce parcours (Ctrl+I)')
        a_props.triggered.connect(self._edit_parcours_props)
        fm.addAction(a_props)

        fm.addSeparator()
        self._recent_menu = fm.addMenu('Fichiers récents JSON')
        self._refresh_recent_menu()

        fm.addSeparator()

        self._act_save = QAction('Enregistrer', self)
        self._act_save.setShortcut('Ctrl+S')
        self._act_save.setToolTip('Enregistrer la trace photo (Ctrl+S)')
        self._act_save.triggered.connect(self._track_save)
        fm.addAction(self._act_save)

        act_save_as = QAction('Enregistrer sous…', self)
        act_save_as.setShortcut('Ctrl+Shift+S')
        act_save_as.setToolTip('Enregistrer la trace photo sous un autre nom (Ctrl+Shift+S)')
        act_save_as.triggered.connect(self._track_save_as)
        fm.addAction(act_save_as)

        fm.addSeparator()

        a2 = QAction('Quitter', self)
        a2.setShortcut('Ctrl+Q')
        a2.triggered.connect(self.close)
        fm.addAction(a2)

        nm = mb.addMenu('Navigation')
        a_goto = QAction('Aller aux coordonnées…', self)
        a_goto.setShortcut('Ctrl+G')
        a_goto.triggered.connect(self._goto_coords)
        nm.addAction(a_goto)

        a_home = QAction('Recentrer la trace', self)
        a_home.setShortcut('Ctrl+R')
        a_home.triggered.connect(lambda: self._map.reset_view())
        nm.addAction(a_home)

        om = mb.addMenu('Outils')
        a_cache_info = QAction('Informations sur le cache…', self)
        a_cache_info.triggered.connect(self._cache_info)
        om.addAction(a_cache_info)

        a_cache_clear = QAction('Vider le cache de tuiles…', self)
        a_cache_clear.triggered.connect(self._cache_clear)
        om.addAction(a_cache_clear)

        hm = mb.addMenu('Aide')
        a3 = QAction('À propos', self)
        a3.triggered.connect(self._about)
        hm.addAction(a3)

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
        if urls:
            self._load(urls[0].toLocalFile())

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
        self._chart_alt.load(gps.distances, gps.alts,   'Altitude (m)')
        self._chart_spd.load(gps.distances, gps.speeds, 'Vitesse (km/h)')
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
        self._chart_alt.load(self._gps.distances, self._gps.alts,    'Altitude (m)')
        self._chart_spd.load(self._gps.distances, self._gps.speeds,  'Vitesse (km/h)')
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
            series_alt.append((gps.distances, gps.alts,    gps.filename, color))
            series_spd.append((gps.distances, gps.speeds,  gps.filename, color))
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
        self._btn_color.setText(f'🎨  {labels.get(mode, "Trace")}')
        self._map.set_track_mode(mode)

    # ── Fichiers récents ─────────────────────────────────────────────

    def _load_recent(self) -> list:
        try:
            if _RECENT_FILE.exists():
                return json.loads(_RECENT_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
        return []

    def _save_recent(self, files: list):
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _RECENT_FILE.write_text(
                json.dumps(files, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _add_to_recent(self, filepath: str):
        files = self._load_recent()
        filepath = os.path.abspath(filepath)
        if filepath in files:
            files.remove(filepath)
        files.insert(0, filepath)
        files = [f for f in files if os.path.exists(f)][:_MAX_RECENT]
        self._save_recent(files)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        files = self._load_recent()
        if not files:
            a = QAction('(aucun)', self)
            a.setEnabled(False)
            self._recent_menu.addAction(a)
            return
        for fp in files:
            label = os.path.basename(fp)
            a = QAction(label, self)
            a.setToolTip(fp)
            a.triggered.connect(lambda checked=False, p=fp: self._apply_track_json(Path(p)))
            self._recent_menu.addAction(a)
        self._recent_menu.addSeparator()
        clear_a = QAction('Effacer la liste', self)
        clear_a.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear_a)

    def _clear_recent(self):
        self._save_recent([])
        self._refresh_recent_menu()

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
            'label':  '🗺  OpenStreetMap',
            'short':  'OSM',
            'headers': {},
        },
        'esri': {
            'source': cx.providers.Esri.WorldImagery,
            'label':  '🛰  Satellite (Esri)',
            'short':  'Satellite Esri',
            'headers': {},
        },
        'ign_ortho': {
            'source':  _IGN_BASE + '&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&FORMAT=image/jpeg',
            'label':  '🛰  Orthophoto IGN',
            'short':  'Orthophoto IGN',
            'headers': {'User-Agent': 'GPS-Viewer/1.0'},
        },
        'ign_plan': {
            'source':  _IGN_BASE + '&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&FORMAT=image/png',
            'label':  '🗾  Plan IGN',
            'short':  'Plan IGN',
            'headers': {'User-Agent': 'GPS-Viewer/1.0'},
        },
    }

    def _select_tiles(self, key: str):
        info = self._TILE_SOURCES[key]
        self._map.set_tile_source(info['source'], info.get('headers', {}))
        self._btn_tiles.setText(f"🗺  {info['short']}")

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

    # ── Annotations photo ─────────────────────────────────────────────

    def _on_photo_clicked(self, index: int):
        """Ouvre la photo en plein format ; sauvegarde titre/description ; supprime si demandé."""
        if index >= len(self._map._photo_data):
            return
        entry = self._map._photo_data[index]
        orig  = entry['orig_path']
        if not Path(orig).exists():
            QMessageBox.warning(self, 'Fichier introuvable',
                                f'La photo originale est introuvable :\n{orig}')
            return
        dlg = PhotoViewDialog(
            orig, entry['lat'], entry['lon'],
            entry.get('titre', ''), entry.get('description', ''),
            thumb_path=entry.get('thumb_path', ''), parent=self)
        dlg.exec_()
        if dlg.deletion_requested:
            self._delete_photo(index)
        else:
            new_titre = dlg._titre_edit.text().strip()
            new_desc  = dlg._desc_edit.toPlainText().strip()
            title_changed = (new_titre != entry.get('titre', '')
                             or new_desc != entry.get('description', ''))
            if title_changed:
                self._map._photo_data[index]['titre']       = new_titre
                self._map._photo_data[index]['description'] = new_desc
                self._save_track_json()
            if dlg.rotation_applied:
                self._map.reload_photo_annotations()
                self._sb.showMessage('Photo pivotée et miniature mise à jour.')
            elif title_changed:
                self._sb.showMessage('Annotations photo mises à jour.')

    def _delete_photo(self, index: int):
        """Supprime fichiers, artistes carte et entrée JSON pour l'annotation index."""
        if index >= len(self._map._photo_data):
            return
        entry = self._map._photo_data[index]

        # Suppression des fichiers
        for key in ('orig_path', 'thumb_path'):
            p = Path(entry.get(key, ''))
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        # Retrait des artistes de la carte
        if index < len(self._map._photo_artists):
            for art in self._map._photo_artists[index]:
                try:
                    art.remove()
                except Exception:
                    pass
            self._map._photo_artists.pop(index)

        self._map._photo_data.pop(index)
        self._map.draw_idle()

        # Mise à jour du JSON
        self._save_track_json()
        self._sb.showMessage(
            f'Photo supprimée : {Path(entry["orig_path"]).name}')

    def _on_photo_requested(self, x_m: float, y_m: float):
        """Clic en mode photo : ouvre le sélecteur, copie et affiche la photo."""
        from PIL import Image as PilImage
        lat, lon = _webmerc_to_latlon(x_m, y_m)
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choisir une photo', os.getcwd(),
            'Images (*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp)'
            ';;Tous les fichiers (*)')
        if not path:
            return
        try:
            orig_path, thumb_path = self._save_photo(path)
        except Exception as exc:
            QMessageBox.critical(self, 'Erreur photo',
                                 f'Impossible de traiter la photo :\n{exc}')
            return
        self._map.add_photo_annotation(
            x_m, y_m, lat, lon, str(orig_path), str(thumb_path))
        self._save_track_json()
        self._sb.showMessage(
            f'Photo ajoutée : {Path(orig_path).name}'
            f'  •  {lat:.6f}° N  {lon:.6f}° E')

    def _save_photo(self, src_path: str):
        """Copie l'original et crée la miniature dans tracks/images/."""
        from PIL import Image as PilImage
        _TRACKS_IMG_DIR.mkdir(parents=True, exist_ok=True)
        ts  = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        ext = Path(src_path).suffix.lower() or '.jpg'
        i   = 1
        while (_TRACKS_IMG_DIR / f'photo_{ts}_{i:03d}{ext}').exists():
            i += 1
        orig_dest  = _TRACKS_IMG_DIR / f'photo_{ts}_{i:03d}{ext}'
        thumb_dest = _TRACKS_IMG_DIR / f'photo_{ts}_{i:03d}_thumb.jpg'
        shutil.copy2(src_path, orig_dest)
        img = PilImage.open(src_path).convert('RGB')
        img.thumbnail((80, 80), PilImage.LANCZOS)
        img.save(thumb_dest, 'JPEG', quality=85)
        return orig_dest, thumb_dest

    def _save_track_json(self):
        """Sauvegarde toutes les positions photo dans le fichier de trace actif."""
        self._current_track_path.parent.mkdir(parents=True, exist_ok=True)
        photos = [
            {
                'lat':         round(e['lat'], 8),
                'lon':         round(e['lon'], 8),
                'file':        os.path.abspath(e['orig_path']),
                'thumb':       os.path.abspath(e['thumb_path']),
                'titre':       e.get('titre', ''),
                'description': e.get('description', ''),
                'angle':       e.get('angle'),
            }
            for e in self._map._photo_data
        ]
        data = {
            'titre':       self._parcours_titre,
            'description': self._parcours_description,
            'gps_files':   [os.path.abspath(g.filepath) for g in self._gps_list],
            'photos':      photos,
        }
        self._current_track_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8')
        self._persist_track_path()
        self._update_track_title()

    def _resolve_media_path(self, path_str: str) -> str | None:
        """Résout un chemin media en chemin absolu existant.

        Essaie dans l'ordre : absolu, relatif au JSON, relatif au CWD.
        """
        if not path_str:
            return None
        p = Path(path_str)
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
            return
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
                        or item.get('file', '')
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

            # Réinitialise la liste GPS et le sélecteur de trace
            self._gps_list = []
            self._gps      = None
            self._track_combo.blockSignals(True)
            self._track_combo.clear()
            self._track_combo.blockSignals(False)
            self._track_sel_action.setVisible(False)
            self._track_sel_sep.setVisible(False)

            for gps_file in gps_files:
                if Path(gps_file).exists():
                    self._load(gps_file)

        except Exception:
            pass

    # ── Ouverture / enregistrement de la trace ────────────────────────

    def _resolve_startup_track(self) -> Path:
        """Retourne le dernier fichier JSON utilisé, ou le chemin par défaut."""
        try:
            if _LAST_TRACK_FILE.exists():
                p = Path(_LAST_TRACK_FILE.read_text(encoding='utf-8').strip())
                if p.exists():
                    return p
        except Exception:
            pass
        return _TRACKS_JSON

    def _persist_track_path(self):
        """Sauvegarde le chemin du fichier de trace actif pour le prochain démarrage."""
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _LAST_TRACK_FILE.write_text(
                str(self._current_track_path), encoding='utf-8')
        except Exception:
            pass

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
        win._load(sys.argv[1])

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
