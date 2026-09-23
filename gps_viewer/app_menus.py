"""
app_menus.py — MenusMixin : construction de la barre d'outils et de la
               barre de menus de la fenêtre principale.
               Extrait de gps_viewer.py (MainWindow en hérite) pour garder
               ce dernier plus lisible.
"""

from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import (QAction, QComboBox, QHBoxLayout, QLabel, QMenu,
                             QToolBar, QToolButton, QWidget)


class MenusMixin:
    """Barre d'outils et menus de MainWindow.

    Mixin pour MainWindow — les actions sont connectées à des slots définis
    dans gps_viewer.MainWindow (_open_dialog, _goto_coords, _select_tiles…)
    et dans les autres mixins.
    """

    # ── Barre d'outils ───────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar(self)
        self._tb = tb
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setStyleSheet('QToolBar { spacing: 4px; padding: 3px 6px; '
                         'background: #f0f0f0; border-bottom: 1px solid #ccc; }')
        self.addToolBar(tb)

        act_open = QAction('☰  Trace GPS', self)
        act_open.setShortcut('Ctrl+O')
        act_open.setToolTip('Ajouter une trace GPS NMEA (Ctrl+O)')
        act_open.triggered.connect(self._open_dialog)
        tb.addAction(act_open)

        act_home = QAction('⌂  Recentrer', self)
        act_home.setShortcut('Ctrl+R')
        act_home.setToolTip('Revenir à la vue initiale (Ctrl+R)')
        act_home.triggered.connect(lambda: self._map.reset_view())
        tb.addAction(act_home)

        act_goto = QAction('◉  Coordonnées', self)
        act_goto.setShortcut('Ctrl+G')
        act_goto.setToolTip('Naviguer vers des coordonnées GPS (Ctrl+G)')
        act_goto.triggered.connect(self._goto_coords)
        tb.addAction(act_goto)

        self._btn_tiles = QToolButton()
        self._btn_tiles.setText('▦  Fond de carte')
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
        self._btn_color.setText('◆  Trace')
        self._btn_color.setToolTip('Coloration de la trace')
        self._btn_color.setPopupMode(QToolButton.InstantPopup)
        menu_color = QMenu(self._btn_color)
        for mode, label in [('flat', '— Couleur unie'),
                             ('altitude', '▲  Altitude'),
                             ('speed',    '⚡  Vitesse')]:
            a = QAction(label, self)
            a.triggered.connect(lambda c=False, m=mode: self._select_track_mode(m))
            menu_color.addAction(a)
        self._btn_color.setMenu(menu_color)
        tb.addWidget(self._btn_color)

        # ── Mesure de distance ───────────────────────────────────────
        self._act_meas = QAction('↔  Mesure', self)
        self._act_meas.setCheckable(True)
        self._act_meas.setShortcut('Ctrl+D')
        self._act_meas.setToolTip(
            'Mesure de distance clic-à-clic (Ctrl+D)  •  Échap pour annuler')
        tb.addAction(self._act_meas)

        # ── Annotation photo ─────────────────────────────────────────
        self._act_photo = QAction('◇  Photo', self)
        self._act_photo.setCheckable(True)
        self._act_photo.setToolTip(
            'Annoter la carte avec une photo (P)  •  Clic pour choisir la position')
        tb.addAction(self._act_photo)

        # ── Annotation note ──────────────────────────────────────────
        self._act_note = QAction('✎  Note', self)
        self._act_note.setCheckable(True)
        self._act_note.setToolTip(
            'Ajouter une note sur la carte (N)  •  Clic pour choisir la position')
        tb.addAction(self._act_note)

        # ── Grille / miniature ───────────────────────────────────────
        act_grid = QAction('⊞  Grille', self)
        act_grid.setCheckable(True)
        act_grid.setToolTip('Afficher la grille lat/lon (Ctrl+L)')
        act_grid.setShortcut('Ctrl+L')
        act_grid.toggled.connect(lambda v: self._map.toggle_grid(v))
        tb.addAction(act_grid)

        act_ov = QAction('⬢  Miniature', self)
        act_ov.setCheckable(True)
        act_ov.setToolTip('Afficher la miniature de localisation (Ctrl+M)')
        act_ov.setShortcut('Ctrl+M')
        act_ov.toggled.connect(lambda v: self._map.toggle_overview(v))
        tb.addAction(act_ov)

        act_contours = QAction('▲  Courbes', self)
        act_contours.setCheckable(True)
        act_contours.setToolTip(
            'Afficher les courbes de niveau SRTM (30 m)\n'
            'Premier affichage : téléchargement des tuiles SRTM (~quelques Mo)')
        act_contours.toggled.connect(lambda v: self._map.toggle_contours(v))
        tb.addAction(act_contours)

        # ── Vue 3D ──────────────────────────────────────────────────
        act_3d = QAction('◈  Vue 3D', self)
        act_3d.setShortcut('Ctrl+3')
        act_3d.setToolTip('Afficher la trace en 3D (altitude) (Ctrl+3)')
        act_3d.triggered.connect(self._open_3d_view)
        tb.addAction(act_3d)

        # ── Réception LoRa live ──────────────────────────────────────
        tb.addSeparator()

        self._act_lora = QAction('◎  LoRa Live', self)
        self._act_lora.setCheckable(True)
        self._act_lora.setToolTip(
            'Démarrer / arrêter la réception GPS en temps réel\n'
            'via le récepteur LoRa branché en USB')
        self._act_lora.toggled.connect(self._on_lora_toggled)
        tb.addAction(self._act_lora)

        # Suivi de la position live (visible seulement pendant LoRa Live)
        self._act_follow = QAction('➤  Suivre position', self)
        self._act_follow.setCheckable(True)
        self._act_follow.setChecked(True)
        self._act_follow.setToolTip(
            'La carte suit la position reçue en direct\n'
            '(désactivé automatiquement si vous déplacez la carte)')
        self._act_follow.setVisible(False)
        tb.addAction(self._act_follow)

        self._lbl_lora_status = QLabel()
        self._lbl_lora_status.setStyleSheet(
            'color:#e67e22; padding:0 6px; font-size:11px; font-weight:bold;')
        self._lbl_lora_status.setVisible(False)
        tb.addWidget(self._lbl_lora_status)

        # ── Sélecteur de trace active pour les graphiques ────────────
        # Le séparateur et le widget sont gérés via leur QWidgetAction
        # (setVisible sur le QWidget lui-même est ignoré dans un QToolBar)
        _track_selector = QWidget()
        _sel_layout = QHBoxLayout(_track_selector)
        _sel_layout.setContentsMargins(4, 0, 4, 0)
        _sel_layout.setSpacing(4)
        _lbl_sel = QLabel('▧ Graphiques :')
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

    # ── Barre de menus ───────────────────────────────────────────────

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

        nm.addSeparator()
        self._act_fullscreen = QAction('Plein écran (carte)', self)
        self._act_fullscreen.setCheckable(True)
        self._act_fullscreen.setShortcut('F11')
        self._act_fullscreen.toggled.connect(self._set_fullscreen)
        nm.addAction(self._act_fullscreen)

        om = mb.addMenu('Outils')
        a_monitor = QAction('Données GPS reçues (LoRa)…', self)
        a_monitor.setShortcut('Ctrl+Shift+L')
        a_monitor.setToolTip('Fenêtre des données GPS reçues en direct par le récepteur LoRa')
        a_monitor.triggered.connect(self._show_lora_monitor)
        om.addAction(a_monitor)
        om.addSeparator()

        a_cache_info = QAction('Informations sur le cache…', self)
        a_cache_info.triggered.connect(self._cache_info)
        om.addAction(a_cache_info)

        a_cache_clear = QAction('Vider le cache de tuiles…', self)
        a_cache_clear.triggered.connect(self._cache_clear)
        om.addAction(a_cache_clear)

        pm = mb.addMenu('Paramétrage')

        self._act_cursor_info = QAction('Afficher distance parcourue / restante', self)
        self._act_cursor_info.setCheckable(True)
        self._act_cursor_info.setChecked(True)
        self._act_cursor_info.setToolTip(
            'Affiche la boîte distance parcouru / restant\n'
            'à côté du curseur sur la carte et les graphiques')
        self._act_cursor_info.toggled.connect(self._on_toggle_cursor_info)
        pm.addAction(self._act_cursor_info)

        pm.addSeparator()
        a_prefs = QAction('Préférences…', self)
        a_prefs.setShortcut('Ctrl+,')
        a_prefs.triggered.connect(self._on_prefs)
        pm.addAction(a_prefs)

        hm = mb.addMenu('Aide')
        a3 = QAction('À propos', self)
        a3.triggered.connect(self._about)
        hm.addAction(a3)

        # En plein écran, la barre d'outils et la barre de menus sont masquées :
        # Qt désactive alors les raccourcis de leurs actions. On rattache les
        # actions à raccourci à la fenêtre elle-même pour qu'ils restent actifs.
        for act in self._tb.actions() + [a for m in mb.findChildren(QMenu)
                                         for a in m.actions()]:
            if not act.shortcut().isEmpty():
                self.addAction(act)
