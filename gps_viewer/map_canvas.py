"""
map_canvas.py — MapCanvas et constantes visuelles.
                Infrastructure de tuiles (cache, threads) dans map_tiles.py,
                outils de la carte (mesure, photos, notes) dans map_tools.py.
"""

import math

import numpy as np
import matplotlib
matplotlib.use('Qt5Agg')
matplotlib.rcParams['keymap.pan']     = []   # libère 'p' pour le mode annotation photo
matplotlib.rcParams['keymap.forward'] = []   # libère 'v' pour l'indicateur œil
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.collections import LineCollection
import matplotlib.colors as mcolors
import contextily as cx

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QSizePolicy, QApplication,
                              QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
                              QLabel, QComboBox, QSlider)

from gps_nmea import (GPSData, to_webmerc, _webmerc_to_latlon, WEB_MERC_R,
                       parse_time_s, _fmt_dist, _fmt_elapsed)  # noqa: F401 — réexportés
from map_tiles import (  # noqa: F401 — _TILE_CACHE_DIR/_cache_size_mb/_retire_thread réexportés
    _TILE_CACHE_DIR, _cache_size_mb, _retire_thread,
    _douglas_peucker_mask, _ContourWorker,
    TileLoader, TILE_PX, tile_size_m, tile_range, tiles_extent,
)
from map_tools import MeasureToolMixin, PhotoToolMixin, NoteToolMixin

# ── Couleurs ─────────────────────────────────────────────────────────
C_TRACK   = '#1a6fbf'
C_CURSOR  = '#e74c3c'
C_START   = '#2ecc71'
C_END     = '#e74c3c'

_TRACK_PALETTE = ['#1a6fbf', '#e74c3c', '#27ae60', '#f39c12',
                  '#9b59b6', '#16a085', '#e67e22', '#2c3e50']

# ── Colormaps pour les modes de trace ────────────────────────────────
_CMAP_ALT = mcolors.LinearSegmentedColormap.from_list(
    'alt', ['#3949ab', '#26c6da', '#43a047', '#fdd835', '#e53935'])
_CMAP_SPD = mcolors.LinearSegmentedColormap.from_list(
    'spd', ['#27ae60', '#f39c12', '#e74c3c'])


# ══════════════════════════════════════════════════════════════════════
#  Canvas Carte  (matplotlib + contextily OSM)
# ══════════════════════════════════════════════════════════════════════

class MapCanvas(MeasureToolMixin, PhotoToolMixin, NoteToolMixin, FigureCanvas):
    tile_loading           = pyqtSignal(bool)   # True = début, False = fin
    measure_updated        = pyqtSignal(str)    # message status bar
    measure_mode_cancelled = pyqtSignal()       # Échap appuyé en mode mesure
    photo_requested        = pyqtSignal(float, float)  # x_m, y_m Web Mercator
    photo_mode_changed     = pyqtSignal(bool)   # basculement mode photo
    photo_clicked          = pyqtSignal(int)    # index dans _photo_data
    photo_eye_changed      = pyqtSignal(int)    # angle œil modifié → sauvegarder
    note_requested         = pyqtSignal(float, float)  # x_m, y_m Web Mercator
    note_mode_changed      = pyqtSignal(bool)   # basculement mode note
    note_clicked           = pyqtSignal(int)    # index dans _note_data
    playback_index_changed = pyqtSignal(int)    # lecture automatique : index courant

    def __init__(self):
        self.fig = Figure(facecolor='#2b2b2b')
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_axis_off()
        self._cursor_dot        = None
        self._cursor_annot      = None   # annotation distance parcouru/restant
        self._show_cursor_info  = True   # activé via Paramétrage
        self._gps: GPSData | None = None
        self._gps_list: list      = []
        self._default_lim = None   # (xlim, ylim) pour reset
        self._tile_source   = cx.providers.OpenStreetMap.Mapnik
        # OSM bloque le User-Agent aléatoire par défaut de contextily
        # ('contextily-<uuid>') — voir _TILE_SOURCES dans gps_viewer.py.
        self._tile_headers  = {'User-Agent': 'GPS-Viewer/1.0'}

        # ── Chargement des tuiles (tuile par tuile, voir map_tiles) ──
        self._tiles = TileLoader(self)
        self._tiles.set_source(self._tile_source, self._tile_headers)
        self._tiles.tile_ready.connect(self._on_tile_ready)
        self._tiles.tile_failed.connect(self._on_tile_failed)
        # Mosaïque en cours d'affichage : dict(src, z, x0, x1, y0, y1, arr,
        # im, missing, errors) ; l'image précédente (_tile_im_back) reste
        # affichée dessous tant que la nouvelle mosaïque est incomplète.
        self._mosaic: dict | None = None
        self._tile_im_back = None

        # ── Paramètres visuels configurables ────────────────────────
        self._track_linewidth   = 2.5   # épaisseur des traces (px)
        self._map_alpha         = 1.0   # opacité du fond de carte 0–1
        self._photo_zoom        = 0.8   # zoom miniature photo
        self._photo_cross_size  = 16    # taille croix photo (markersize)
        self._cursor_dot_size   = 12    # diamètre curseur rouge (markersize)
        self._autopan_margin_px = 0     # marge déclenchement pan (px, 0=bord)

        # ── Simplification / coloration de trace ────────────────────
        self._track_artists: list    = []   # un artist (ligne) par GPSData
        self._track_markers: list    = []   # [(start, end), ...] par trace
        self._track_filter_idx: int | None = None  # None = toutes visibles
        self._track_mode    = 'flat'    # 'flat' | 'altitude' | 'speed'
        self._colorbar_ax   = None      # inset axes pour la colorbar

        # ── Miniature de localisation ────────────────────────────────
        self._ov_ax        = None   # inset axes de la miniature
        self._ov_rect      = None   # patch rectangle vue courante
        self._ov_visible   = False

        # ── Grille de coordonnées ────────────────────────────────────
        self._grid_artists = []     # tous les artists de la grille
        self._grid_visible = False

        # ── Indicateur de chargement ─────────────────────────────────
        self._loading_text = None  # text artist, None si axes vidés
        self._error_text   = None  # idem, pour « Tuiles indisponibles »

        # ── Mesure de distance ───────────────────────────────────────
        self._measure_mode   = False
        self._meas_pts       = []    # [(x_m, y_m), …] points placés
        self._meas_artists   = []    # artists permanents à nettoyer
        self._meas_rubber    = None  # ligne rubber-band live
        self._meas_lbl_live  = None  # label distance live
        self._meas_pending   = None  # (x, y) en attente de confirmation

        # Timer anti-dblclick : retarde chaque clic de 200 ms pour
        # distinguer un simple clic d'un double-clic.
        self._meas_timer = QTimer(self, singleShot=True, interval=200)
        self._meas_timer.timeout.connect(self._meas_commit_pending)

        # ── Mode annotation photo ────────────────────────────────────
        self._photo_mode        = False
        self._photo_data        = []   # [{x_m,y_m,lat,lon,orig_path,thumb_path,angle}, …]
        self._photo_artists     = []   # artistes par annotation (parallèle à _photo_data)
        self._hovered_photo_idx = None # index de l'annotation sous le curseur

        # ── Mode annotation note ─────────────────────────────────────
        self._note_mode         = False
        self._note_data         = []   # [{x_m,y_m,lat,lon,titre,description}, …]
        self._note_artists      = []   # artistes par note (parallèle à _note_data)

        # ── État pan ────────────────────────────────────────────────
        self._pan_xy   = None   # position pixel au début du drag
        self._pan_lims = None   # (xlim, ylim) au début du drag

        # ── Courbes de niveau ────────────────────────────────────────
        self._contours_enabled  = False
        self._contour_worker: _ContourWorker | None = None
        self._contour_sets      = []   # ContourSet objects (cs.remove() matplotlib 3.8+)
        self._contour_labels    = []   # Text objects des étiquettes (remove séparé)
        self._contour_req       = 0    # compteur de requête — invalide les résultats périmés

        # ── Timer rechargement tuiles (débounce molette 120 ms) ─────
        self._tile_timer = QTimer(singleShot=True, interval=120)
        self._tile_timer.timeout.connect(self._reload_tiles)
        # Pendant un glisser (pan) : tuiles demandées toutes les 150 ms
        self._pan_tile_timer = QTimer(self, singleShot=True, interval=150)
        self._pan_tile_timer.timeout.connect(self._request_tiles)
        # Rendu regroupé des tuiles qui arrivent (un rendu matplotlib coûte
        # ~0,1 s : on en fait au plus un toutes les 60 ms pendant le
        # chargement ; les tuiles lues sur disque tombent dans le premier)
        self._tile_draw_timer = QTimer(self, singleShot=True, interval=60)
        self._tile_draw_timer.timeout.connect(self.draw_idle)

        # ── Garde-fou : signale un chargement de tuiles trop long ───
        # (ex. réseau indisponible) au lieu de laisser « Chargement… »
        # affiché indéfiniment si le serveur ne répond jamais.
        self._tile_watchdog = QTimer(self, singleShot=True, interval=20_000)
        self._tile_watchdog.timeout.connect(self._on_tile_timeout)

        # ── Timer courbes de niveau (débounce 900 ms) ────────────────
        self._contour_timer = QTimer(singleShot=True, interval=900)
        self._contour_timer.timeout.connect(self._request_contours)

        # ── Lecture automatique (playback) ───────────────────────────
        self._play_index        = 0
        self._play_speed        = 1    # points sautés par tick
        self._playing           = False
        self._scrub_was_playing = False
        self._play_timer  = QTimer(self, interval=100)
        self._play_timer.timeout.connect(self._playback_tick)
        self._play_bar    = self._build_play_bar()
        self._play_bar.setVisible(False)

        # ── Mode réception live (LoRa) ───────────────────────────────
        self._live_line:  object = None   # Line2D de la trace en cours
        self._live_dot:   object = None   # Point GPS courant
        self._live_xs:    list   = []
        self._live_ys:    list   = []
        self._live_color: str    = '#e67e22'

        # ── Événements souris / clavier ──────────────────────────────
        self.mpl_connect('scroll_event',         self._on_scroll)
        self.mpl_connect('button_press_event',   self._on_press)
        self.mpl_connect('motion_notify_event',  self._on_motion)
        self.mpl_connect('button_release_event', self._on_release)
        self.mpl_connect('key_press_event',      self._on_key)

        self.setCursor(Qt.OpenHandCursor)
        self._welcome()

    def _welcome(self):
        self.ax.set_facecolor('#2b2b2b')
        self.ax.text(0.5, 0.5,
                     'Ajouter une trace GPS\n(Fichier → Ajouter une trace GPS  ou  Ctrl+O)',
                     transform=self.ax.transAxes, ha='center', va='center',
                     color='#888', fontsize=13, fontfamily='monospace')
        self.draw()

    # ── Chargement initial ───────────────────────────────────────────

    def load(self, gps: GPSData):
        self._gps = gps
        self._gps_list     = [gps]
        self._loading_text = None
        self._error_text   = None
        self._track_artists    = []
        self._track_markers    = []
        self._track_filter_idx = None
        self._colorbar_ax  = None
        self._ov_ax        = None
        self._ov_rect      = None
        self._grid_artists = []
        self._meas_pts     = []
        self._meas_artists = []
        self._meas_rubber  = self._meas_lbl_live = None
        self._meas_pending = None
        self._meas_timer.stop()
        self.ax.cla()
        self.ax.set_axis_off()
        self.ax.set_aspect('equal', adjustable='datalim')

        mg = max(100,
                 (gps.xs.max() - gps.xs.min()) * 0.18,
                 (gps.ys.max() - gps.ys.min()) * 0.18)
        xlim = (gps.xs.min()-mg, gps.xs.max()+mg)
        ylim = (gps.ys.min()-mg, gps.ys.max()+mg)
        self._default_lim = (xlim, ylim)
        self.ax.set_xlim(xlim)
        self.ax.set_ylim(ylim)

        # Trace immédiatement visible ; tuiles en arrière-plan
        self._contour_sets   = []
        self._contour_labels = []
        self._draw_track()
        self._redraw_photos()
        self._redraw_notes()
        self._request_tiles()
        if self._contours_enabled:
            self._contour_timer.start()

        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.draw()
        self._playback_show(gps)

    def _draw_track(self):
        self._track_artists = []
        self._track_markers = []
        for i, gps in enumerate(self._gps_list):
            color  = _TRACK_PALETTE[i % len(_TRACK_PALETTE)]
            artist = self._add_track_artist_for(gps, color)
            self._track_artists.append(artist)
            s, = self.ax.plot(gps.xs[0],  gps.ys[0],  'o',
                              color=color, markersize=11, zorder=7,
                              markeredgecolor='white', markeredgewidth=2,
                              label=gps.filename)
            e, = self.ax.plot(gps.xs[-1], gps.ys[-1], 's',
                              color=color, markersize=10, zorder=7,
                              markeredgecolor='white', markeredgewidth=2)
            self._track_markers.append((s, e))
        self.ax.legend(loc='upper left', fontsize=9,
                       framealpha=0.85, fancybox=True)
        self._cursor_dot, = self.ax.plot([], [], 'o',
            color=C_CURSOR, markersize=self._cursor_dot_size, zorder=10,
            markeredgecolor='white', markeredgewidth=1.5, visible=False)
        self._cursor_annot = self.ax.annotate(
            '', xy=(0, 0), xycoords='data',
            xytext=(14, 8), textcoords='offset points',
            color='white', fontsize=8.5,
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#1a2535',
                      edgecolor=C_CURSOR, alpha=0.92),
            zorder=12, visible=False)
        if self._track_mode != 'flat':
            self._draw_colorbar()
        self._apply_track_filter()

    def _add_track_artist_for(self, gps: GPSData, color: str):
        """Crée et retourne l'artist de trace pour un GPSData donné."""
        if self._track_mode == 'flat':
            xs, ys = self._simplified_track_for(gps)
            line, = self.ax.plot(
                xs, ys, color=color, linewidth=self._track_linewidth, zorder=5,
                solid_capstyle='round', solid_joinstyle='round')
            return line

        # Modes gradient : altitude ou vitesse
        if self._track_mode == 'altitude':
            raw = np.array([p['alt'] if p['alt'] is not None else 0
                            for p in gps.points], dtype=float)
            cmap = _CMAP_ALT
        else:  # speed
            raw  = np.array([s if s is not None else 0
                             for s in gps.speeds], dtype=float)
            cmap = _CMAP_SPD

        xs, ys, vals = self._simplified_track_values_for(gps, raw)
        vmin, vmax = vals.min(), vals.max()
        if vmin == vmax:
            vmax = vmin + 1

        pts  = np.array([xs, ys]).T.reshape(-1, 1, 2)
        segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
        seg_vals = (vals[:-1] + vals[1:]) / 2

        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
        lc   = LineCollection(segs, cmap=cmap, norm=norm,
                              linewidth=self._track_linewidth, zorder=5,
                              capstyle='round', joinstyle='round')
        lc.set_array(seg_vals)
        self.ax.add_collection(lc)
        return lc

    def _draw_colorbar(self):
        """Ajoute une colorbar en inset."""
        if self._colorbar_ax is not None:
            try:
                self._colorbar_ax.remove()
            except Exception:
                pass
        self._colorbar_ax = self.fig.add_axes([0.015, 0.18, 0.018, 0.30])
        if self._track_mode == 'altitude':
            raw   = np.array([p['alt'] if p['alt'] is not None else 0
                              for p in self._gps.points], dtype=float)
            cmap  = _CMAP_ALT
            label = 'Alt (m)'
        else:
            raw   = np.array([s if s is not None else 0
                              for s in self._gps.speeds], dtype=float)
            cmap  = _CMAP_SPD
            label = 'Vit (km/h)'
        vmin, vmax = raw.min(), raw.max()
        if vmin == vmax:
            vmax = vmin + 1
        sm = matplotlib.cm.ScalarMappable(
            cmap=cmap, norm=mcolors.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cb = self.fig.colorbar(sm, cax=self._colorbar_ax)
        cb.ax.tick_params(labelsize=7, colors='#555')
        cb.ax.yaxis.set_tick_params(color='#888')
        cb.set_label(label, fontsize=7, color='#555')
        cb.outline.set_edgecolor('#888')

    def _add_tiles(self):
        try:
            cx.add_basemap(self.ax, crs='EPSG:3857',
                           source=self._tile_source,
                           zoom='auto', attribution_size=6,
                           headers=self._tile_headers or None)
        except Exception as e:
            self.ax.set_facecolor('#d9e8f5')
            self.ax.text(0.5, 0.02, f'Tuiles indisponibles : {e}',
                         transform=self.ax.transAxes, ha='center',
                         fontsize=8, color='#c00')

    def set_tile_source(self, source, headers: dict | None = None) -> None:
        """Change la source de tuiles et recharge la carte."""
        self._tile_source  = source
        self._tile_headers = headers or {}
        self._tiles.set_source(source, self._tile_headers)
        if self._default_lim is not None:
            self._reload_tiles()

    # ── Zoom adaptatif ───────────────────────────────────────────────

    _MAX_TILES = 120   # garde-fou : nombre max de tuiles par vue

    def _compute_zoom(self) -> int:
        """Niveau de zoom dont la résolution correspond à celle de l'écran
        (1 pixel de tuile ≈ 1 pixel affiché : ni flou, ni tuiles en trop)."""
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        span_m = xl[1] - xl[0]
        pos    = self.ax.get_position()
        ax_px  = pos.width * self.fig.get_size_inches()[0] * self.fig.dpi
        if span_m <= 0 or ax_px <= 0:
            return 12
        # mètres/pixel d'une tuile au niveau z = tile_size_m(z) / 256
        z = math.ceil(math.log2(tile_size_m(0) * ax_px / (TILE_PX * span_m)) - 0.25)
        z = max(2, min(z, self._tiles.max_zoom))
        while z > 2:
            x0, x1, y0, y1 = tile_range(xl, yl, z)
            if (x1 - x0 + 1) * (y1 - y0 + 1) <= self._MAX_TILES:
                break
            z -= 1
        return z

    # ── Douglas-Peucker ──────────────────────────────────────────────

    def _dp_epsilon(self) -> float:
        """Tolérance en mètres équivalente à ~1.5 pixel dans la vue courante."""
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        pos    = self.ax.get_position()
        fig_sz = self.fig.get_size_inches() * self.fig.dpi
        ax_w   = pos.width  * fig_sz[0]
        ax_h   = pos.height * fig_sz[1]
        if ax_w > 0 and ax_h > 0:
            return max((xl[1]-xl[0])/ax_w, (yl[1]-yl[0])/ax_h) * 1.5
        return 1.0

    def _simplified_track_for(self, gps: GPSData):
        """Retourne (xs, ys) avec Douglas-Peucker si la trace > 500 pts."""
        if gps is None or gps.count < 500:
            return gps.xs, gps.ys
        mask = _douglas_peucker_mask(gps.xs, gps.ys, self._dp_epsilon())
        return gps.xs[mask], gps.ys[mask]

    def _simplified_track_values_for(self, gps: GPSData, values: np.ndarray):
        """Retourne (xs, ys, values) après Douglas-Peucker."""
        if gps is None or gps.count < 500:
            return gps.xs, gps.ys, values
        mask = _douglas_peucker_mask(gps.xs, gps.ys, self._dp_epsilon())
        return gps.xs[mask], gps.ys[mask], values[mask]

    def _redraw_all_tracks(self):
        """Remplace tous les artists de trace avec la simplification courante."""
        for artist in self._track_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._track_artists = []
        if self._colorbar_ax is not None:
            try:
                self._colorbar_ax.remove()
            except Exception:
                pass
            self._colorbar_ax = None
        if not self._gps_list:
            return
        for i, gps in enumerate(self._gps_list):
            color  = _TRACK_PALETTE[i % len(_TRACK_PALETTE)]
            artist = self._add_track_artist_for(gps, color)
            self._track_artists.append(artist)
        if self._track_mode != 'flat' and self._gps is not None:
            self._draw_colorbar()
        self._apply_track_filter()

    def set_track_mode(self, mode: str):
        """Change le mode de coloration : 'flat', 'altitude', 'speed'."""
        self._track_mode = mode
        if self._gps_list:
            self._redraw_all_tracks()
            self.draw_idle()

    # ── Chargement asynchrone des tuiles ─────────────────────────────

    def _request_tiles(self):
        """Affiche la mosaïque de tuiles de la vue courante.

        Les tuiles en mémoire sont posées immédiatement ; les autres sont
        demandées au TileLoader (disque puis réseau, centre de la vue en
        premier) et apparaissent au fur et à mesure (_on_tile_ready)."""
        if self._default_lim is None:
            return
        # aspect 'equal' / adjustable 'datalim' : les limites réelles ne sont
        # recalculées qu'au rendu — sans ça, juste après un set_xlim, zoom et
        # emprise des tuiles seraient calculés sur la vue demandée, pas affichée
        self.ax.apply_aspect()
        self._update_overview()
        if self._grid_visible:
            self._draw_grid()

        z = self._compute_zoom()
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        x0, x1, y0, y1 = tile_range(xl, yl, z)
        src = self._tiles.src_key
        cur = self._mosaic
        if cur is not None and cur['im'] not in self.ax.images:
            cur = self._mosaic = None            # axes vidés (ax.cla())
        if self._tile_im_back is not None and self._tile_im_back not in self.ax.images:
            self._tile_im_back = None
        if (cur is not None and cur['src'] == src and cur['z'] == z
                and (cur['x0'], cur['x1'], cur['y0'], cur['y1']) == (x0, x1, y0, y1)):
            if cur['missing'] - cur['errors'].keys():
                self._tiles.request(self._tile_priority(cur))
            return                               # même mosaïque : rien à refaire

        nx, ny = x1 - x0 + 1, y1 - y0 + 1
        arr = np.zeros((ny * TILE_PX, nx * TILE_PX, 4), dtype=np.uint8)
        missing = set()
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                img = self._tiles.get_cached(z, tx, ty)
                if img is None:
                    missing.add((tx, ty))
                else:
                    self._paste_tile(arr, tx - x0, ty - y0, img)

        # L'image courante devient le fond provisoire si elle est complète
        # (sinon on garde le fond provisoire existant, plus fiable).
        if cur is not None:
            if not cur['missing'] or self._tile_im_back is None:
                self._remove_back_image()
                self._tile_im_back = cur['im']
                self._tile_im_back.set_zorder(-1)
            else:
                cur['im'].remove()

        im = self.ax.imshow(arr, extent=tiles_extent(x0, x1, y0, y1, z),
                            interpolation='bilinear', zorder=0,
                            alpha=self._map_alpha)
        self.ax.set_xlim(xl)
        self.ax.set_ylim(yl)
        self._mosaic = dict(src=src, z=z, x0=x0, x1=x1, y0=y0, y1=y1,
                            arr=arr, im=im, missing=missing, errors={})
        self._clear_tile_error()
        if missing:
            self._show_loading(draw=False)
            self.tile_loading.emit(True)
            self._tiles.request(self._tile_priority(self._mosaic))
            self._tile_watchdog.start()
            self._tile_draw_timer.start()
        else:
            self._mosaic_complete()

    def _tile_priority(self, mosaic: dict) -> list:
        """Tuiles manquantes, de la plus proche du centre de la vue à la plus loin."""
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        ts, half = tile_size_m(mosaic['z']), tile_size_m(0) / 2
        cx_t = ((xl[0] + xl[1]) / 2 + half) / ts - 0.5
        cy_t = (half - (yl[0] + yl[1]) / 2) / ts - 0.5
        todo = mosaic['missing'] - mosaic['errors'].keys()
        return [(mosaic['z'], tx, ty) for tx, ty in
                sorted(todo, key=lambda t: (t[0] - cx_t) ** 2 + (t[1] - cy_t) ** 2)]

    @staticmethod
    def _paste_tile(arr, col: int, row: int, img):
        r, c = row * TILE_PX, col * TILE_PX
        arr[r:r + TILE_PX, c:c + TILE_PX, :3] = img
        arr[r:r + TILE_PX, c:c + TILE_PX, 3]  = 255

    def _remove_back_image(self):
        if self._tile_im_back is not None:
            try:
                self._tile_im_back.remove()
            except Exception:
                pass
            self._tile_im_back = None

    def _clear_tile_error(self):
        """Efface le message « Tuiles indisponibles » et le fond associé,
        laissé par une tentative précédente (source changée, réseau revenu…).
        Sans ça, un seul échec restait affiché indéfiniment par-dessus la
        carte même après un chargement réussi ultérieur."""
        if self._error_text is not None:
            self._error_text.set_visible(False)

    def _mosaic_for(self, src: str, z: int, x: int, y: int):
        m = self._mosaic
        if (m is None or m['src'] != src or m['z'] != z
                or (x, y) not in m['missing'] or m['im'] not in self.ax.images):
            return None
        return m

    def _on_tile_ready(self, src: str, z: int, x: int, y: int, img):
        m = self._mosaic_for(src, z, x, y)
        if m is None:
            return                     # tuile d'une vue quittée (reste en cache)
        self._paste_tile(m['arr'], x - m['x0'], y - m['y0'], img)
        m['missing'].discard((x, y))
        m['errors'].pop((x, y), None)
        m['im'].set_data(m['arr'])
        self._tile_watchdog.start()    # progression : relance le délai de garde
        if not self._tile_draw_timer.isActive():
            self._tile_draw_timer.start()
        self._check_mosaic_done()

    def _on_tile_failed(self, src: str, z: int, x: int, y: int, msg: str):
        m = self._mosaic_for(src, z, x, y)
        if m is None:
            return
        m['errors'][(x, y)] = msg
        self._check_mosaic_done()

    def _check_mosaic_done(self):
        m = self._mosaic
        if m['missing'] and set(m['errors']) != m['missing']:
            return                     # encore des tuiles en route
        if m['errors']:
            n   = len(m['errors'])
            msg = next(iter(m['errors'].values()))
            self._on_tiles_failed(f'{n} tuile(s) — {msg}')
        else:
            self._mosaic_complete()

    def _mosaic_complete(self):
        self._tile_watchdog.stop()
        self._tile_draw_timer.stop()
        self._remove_back_image()
        self._hide_loading()           # → draw_idle
        self.tile_loading.emit(False)

    def _on_tiles_failed(self, msg: str):
        self._tile_watchdog.stop()
        self._tile_draw_timer.stop()
        self._hide_loading()
        self.tile_loading.emit(False)
        self.ax.set_facecolor('#d9e8f5')
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        text = f'Tuiles indisponibles : {msg}'
        if self._error_text is None:
            self._error_text = self.ax.text(
                0.5, 0.02, text,
                transform=self.ax.transAxes, ha='center',
                fontsize=8, color='#c00', zorder=20)
        else:
            self._error_text.set_text(text)
            self._error_text.set_visible(True)
        self.ax.set_xlim(xl)
        self.ax.set_ylim(yl)
        self.draw_idle()

    def _on_tile_timeout(self):
        """Aucune tuile n'est arrivée depuis 20 s alors qu'il en manque.

        Un appel réseau peut rester bloqué côté système (résolution DNS
        notamment, non bornée par le timeout HTTP) ; on informe l'utilisateur
        au lieu de laisser « Chargement des tuiles… » affiché sans fin. Les
        tuiles qui arriveraient plus tard sont tout de même affichées.
        """
        self._on_tiles_failed('délai dépassé — vérifier la connexion réseau')

    def _show_loading(self, draw: bool = True):
        self._clear_tile_error()   # une nouvelle tentative efface l'ancienne erreur
        if self._loading_text is None:
            self._loading_text = self.ax.text(
                0.5, 0.02, 'Chargement des tuiles…',
                transform=self.ax.transAxes, ha='center', va='bottom',
                color='#555', fontsize=9, fontfamily='monospace',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.75),
                zorder=20)
        else:
            self._loading_text.set_visible(True)
        if draw:
            self.draw_idle()

    def _hide_loading(self):
        if self._loading_text is not None:
            self._loading_text.set_visible(False)
        self.draw_idle()

    # ── Miniature de localisation ────────────────────────────────────

    def toggle_overview(self, visible: bool):
        self._ov_visible = visible
        if not visible:
            if self._ov_ax is not None:
                self._ov_ax.set_visible(False)
            self.draw_idle()
            return
        if self._gps is None:
            return
        if self._ov_ax is None:
            self._ov_ax = self.fig.add_axes(
                [0.72, 0.02, 0.265, 0.22], zorder=15)
            self._ov_ax.set_axis_off()
            # equal : Web Mercator a les mêmes unités en X et Y
            self._ov_ax.set_aspect('equal', adjustable='datalim')
            self._ov_ax.patch.set_alpha(0.82)
            self._ov_ax.patch.set_facecolor('#f5f5f5')
            gps = self._gps
            self._ov_ax.plot(gps.xs, gps.ys,
                             color='#7f8c8d', linewidth=1, zorder=1)
            self._ov_ax.plot(gps.xs[0], gps.ys[0], 'o',
                             color=C_START, markersize=4, zorder=2)
            self._ov_ax.plot(gps.xs[-1], gps.ys[-1], 's',
                             color=C_END, markersize=4, zorder=2)
            mg = max((gps.xs.max() - gps.xs.min()) * 0.06,
                     (gps.ys.max() - gps.ys.min()) * 0.06, 100)
            self._ov_ax.set_xlim(gps.xs.min() - mg, gps.xs.max() + mg)
            self._ov_ax.set_ylim(gps.ys.min() - mg, gps.ys.max() + mg)
            for sp in self._ov_ax.spines.values():
                sp.set_edgecolor('#aaa')
                sp.set_linewidth(0.8)
        else:
            self._ov_ax.set_visible(True)
        self._ov_rect = None
        self._update_overview()

    def _update_overview(self):
        if not self._ov_visible or self._ov_ax is None:
            return
        if self._ov_rect is not None:
            self._ov_rect.remove()
            self._ov_rect = None
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        from matplotlib.patches import FancyBboxPatch
        self._ov_rect = FancyBboxPatch(
            (xl[0], yl[0]), xl[1] - xl[0], yl[1] - yl[0],
            boxstyle='square,pad=0',
            linewidth=1.2, edgecolor='#e74c3c',
            facecolor='#e74c3c', alpha=0.18, zorder=3)
        self._ov_ax.add_patch(self._ov_rect)
        self.draw_idle()

    # ── Grille de coordonnées lat/lon ────────────────────────────────

    def toggle_grid(self, visible: bool):
        self._grid_visible = visible
        if visible:
            self._draw_grid()
        else:
            self._clear_grid()
        self.draw_idle()

    def _clear_grid(self):
        for a in self._grid_artists:
            try:
                a.remove()
            except Exception:
                pass
        self._grid_artists = []

    def _draw_grid(self):
        self._clear_grid()
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        lat_s, lon_w = _webmerc_to_latlon(xl[0], yl[0])
        lat_n, lon_e = _webmerc_to_latlon(xl[1], yl[1])
        span_lat = lat_n - lat_s
        span_lon = lon_e - lon_w

        def _nice_step(span):
            nice = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05,
                    0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 45]
            target = span / 5
            for s in nice:
                if s >= target:
                    return s
            return 45

        step_lat = _nice_step(span_lat)
        step_lon = _nice_step(span_lon)

        lat0 = math.ceil(lat_s / step_lat) * step_lat
        lon0 = math.ceil(lon_w / step_lon) * step_lon

        style = dict(color='#444', linewidth=0.55, linestyle='--',
                     alpha=0.55, zorder=6)

        lat = lat0
        while lat <= lat_n + step_lat * 0.01:
            x0, y0 = to_webmerc(lat, lon_w)
            x1, y1 = to_webmerc(lat, lon_e)
            ln, = self.ax.plot([x0, x1], [y0, y1], **style)
            lbl = self.ax.text(
                xl[0] + (xl[1]-xl[0]) * 0.005, y0,
                f'{lat:.4g}°N', fontsize=7, color='#333',
                va='center', zorder=7,
                bbox=dict(facecolor='white', alpha=0.6, pad=1, edgecolor='none'))
            self._grid_artists += [ln, lbl]
            lat += step_lat

        lon = lon0
        while lon <= lon_e + step_lon * 0.01:
            x0, y0 = to_webmerc(lat_s, lon)
            x1, y1 = to_webmerc(lat_n, lon)
            ln, = self.ax.plot([x0, x1], [y0, y1], **style)
            lbl = self.ax.text(
                x0, yl[0] + (yl[1]-yl[0]) * 0.005,
                f'{lon:.4g}°E', fontsize=7, color='#333',
                ha='center', zorder=7, rotation=90,
                bbox=dict(facecolor='white', alpha=0.6, pad=1, edgecolor='none'))
            self._grid_artists += [ln, lbl]
            lon += step_lon

    # ── Rechargement tuiles après zoom/pan ──────────────────────────

    def _reload_tiles(self):
        if self._default_lim is None:
            return
        if any(g.count >= 500 for g in self._gps_list):
            self._redraw_all_tracks()
        for i, entry in enumerate(self._photo_data):
            if entry.get('angle') is not None:
                self._draw_eye(i)
        self._request_tiles()
        if self._contours_enabled:
            self._contour_timer.start()

    # ── Zoom à la molette ────────────────────────────────────────────

    def _on_scroll(self, event):
        if event.inaxes != self.ax or self._default_lim is None:
            return
        factor = 0.65 if event.button == 'up' else 1.55
        xc, yc = event.xdata, event.ydata
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        relx = (xc - xl[0]) / (xl[1] - xl[0])
        rely = (yc - yl[0]) / (yl[1] - yl[0])
        nw = (xl[1] - xl[0]) * factor
        nh = (yl[1] - yl[0]) * factor
        self.ax.set_xlim(xc - nw * relx,       xc + nw * (1 - relx))
        self.ax.set_ylim(yc - nh * rely,        yc + nh * (1 - rely))
        if self._contours_enabled:
            self._contour_req += 1   # invalide tout worker en cours
            if self._contour_sets:
                self._clear_contours()
        self.draw_idle()
        self._tile_timer.start()   # recharge les tuiles 120 ms après le dernier scroll

    # ── Pan (clic gauche + glisser) ──────────────────────────────────

    def _on_press(self, event):
        if self._photo_mode:
            if (event.button == 1 and event.inaxes == self.ax
                    and event.xdata is not None
                    and not getattr(event, 'dblclick', False)):
                self.photo_requested.emit(event.xdata, event.ydata)
            return
        if self._note_mode:
            if (event.button == 1 and event.inaxes == self.ax
                    and event.xdata is not None
                    and not getattr(event, 'dblclick', False)):
                self.note_requested.emit(event.xdata, event.ydata)
            return
        if self._measure_mode:
            if event.button == 1 and event.inaxes == self.ax and event.xdata is not None:
                if getattr(event, 'dblclick', False):
                    # Double-clic : annule le clic simple en attente et finalise
                    self._meas_timer.stop()
                    self._meas_pending = None
                    self._meas_finalize()
                else:
                    # Simple clic : mise en attente 200 ms (anti-dblclick)
                    self._meas_pending = (event.xdata, event.ydata)
                    self._meas_timer.start()
            return
        if event.button == 1 and event.inaxes == self.ax and self._default_lim is not None:
            # Clic sur une note → ouvre le dialogue d'édition
            idx_note = self._find_note_at(event)
            if idx_note is not None:
                self.note_clicked.emit(idx_note)
                return
            # Clic sur une annotation photo (croix ou miniature) → ouvre la visionneuse
            idx = self._find_photo_at(event, check_thumbnail=True)
            if idx is not None:
                self.photo_clicked.emit(idx)
                return
            self._pan_xy   = (event.x, event.y)
            self._pan_lims = (self.ax.get_xlim(), self.ax.get_ylim())
            self.setCursor(Qt.ClosedHandCursor)

    def _on_motion(self, event):
        if self._measure_mode:
            if self._meas_pts and event.inaxes == self.ax and event.xdata is not None:
                self._meas_update_rubber(event.xdata, event.ydata)
            return
        # Focus clavier automatique dès que la souris est sur la carte
        if event.inaxes == self.ax:
            self.setFocus()
        # Suivi de l'annotation survolée (pour v/w/x)
        if not self._photo_mode and event.x is not None:
            if event.inaxes == self.ax:
                self._hovered_photo_idx = self._find_photo_at(event)
            else:
                self._hovered_photo_idx = None
        if self._pan_xy is None or self._default_lim is None:
            return
        dpx = event.x - self._pan_xy[0]
        dpy = event.y - self._pan_xy[1]
        xl0, yl0 = self._pan_lims

        # Conversion pixels → unités de données via la position normalisée des axes
        pos    = self.ax.get_position()
        fig_sz = self.fig.get_size_inches() * self.fig.dpi
        ax_w   = pos.width  * fig_sz[0]
        ax_h   = pos.height * fig_sz[1]
        if ax_w > 0 and ax_h > 0:
            dx = dpx * (xl0[1] - xl0[0]) / ax_w
            dy = dpy * (yl0[1] - yl0[0]) / ax_h
            self.ax.set_xlim(xl0[0] - dx, xl0[1] - dx)
            self.ax.set_ylim(yl0[0] - dy, yl0[1] - dy)
            self.draw_idle()
            if not self._pan_tile_timer.isActive():
                self._pan_tile_timer.start()   # tuiles au fil du glisser

    def _on_release(self, event):
        if self._measure_mode:
            return
        if event.button == 1 and self._pan_xy is not None:
            self._pan_xy = None
            self.setCursor(Qt.OpenHandCursor)
            if self._contours_enabled:
                self._contour_req += 1   # invalide tout worker en cours
                if self._contour_sets:
                    self._clear_contours()
                    self.draw_idle()
            self._reload_tiles()   # reload immédiat à la fin du drag

    # ── Reset vue ───────────────────────────────────────────────────

    def reset_view(self):
        if self._default_lim is None:
            return
        self.ax.set_xlim(self._default_lim[0])
        self.ax.set_ylim(self._default_lim[1])
        self._reload_tiles()

    # ── Navigation vers des coordonnées ─────────────────────────────

    def goto(self, lat: float, lon: float, zoom: int = 16):
        """Centre la carte sur les coordonnées et affiche un repère rouge."""
        cx_m = math.radians(lon) * WEB_MERC_R
        cy_m = math.log(math.tan(math.radians(lat) / 2 + math.pi / 4)) * WEB_MERC_R

        half = 20_037_508.34 / (2 ** max(1, min(zoom, 19))) * 4
        xlim = (cx_m - half, cx_m + half)
        ylim = (cy_m - half, cy_m + half)

        self._gps              = None
        self._gps_list         = []
        self._cursor_dot       = None
        self._cursor_annot     = None
        self._loading_text     = None
        self._error_text       = None
        self._track_artists    = []
        self._track_markers    = []
        self._track_filter_idx = None
        self._colorbar_ax      = None
        self._ov_ax        = None
        self._ov_rect      = None
        self._grid_artists = []
        self._meas_pts     = []
        self._meas_artists = []
        self._meas_rubber  = self._meas_lbl_live = None
        self._meas_pending = None
        self._meas_timer.stop()
        self._default_lim  = (xlim, ylim)

        self.ax.cla()
        self.ax.set_axis_off()
        self.ax.set_aspect('equal', adjustable='datalim')
        self.ax.set_xlim(xlim)
        self.ax.set_ylim(ylim)

        self.ax.plot(cx_m, cy_m, 'v', color='#e74c3c', markersize=22,
                     zorder=10, markeredgecolor='white', markeredgewidth=2)
        self.ax.plot(cx_m, cy_m, 'o', color='#e74c3c', markersize=7,
                     zorder=11, markeredgecolor='white', markeredgewidth=1.5)

        self._redraw_photos()
        self._redraw_notes()
        self._request_tiles()
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.draw()

    # ── Affichage centré sur les photos (sans trace GPS) ─────────────

    def center_on_photos(self):
        """Centre la carte sur les annotations photo et charge les tuiles."""
        if not self._photo_data:
            return
        xs = [e['x_m'] for e in self._photo_data]
        ys = [e['y_m'] for e in self._photo_data]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        mg = max(500, (xmax - xmin) * 0.35, (ymax - ymin) * 0.35)
        xlim = (xmin - mg, xmax + mg)
        ylim = (ymin - mg, ymax + mg)

        self._loading_text     = None
        self._error_text       = None
        self._gps              = None
        self._gps_list         = []
        self._cursor_dot       = None
        self._cursor_annot     = None
        self._track_artists    = []
        self._track_markers    = []
        self._track_filter_idx = None
        self._colorbar_ax      = None
        self._ov_ax            = None
        self._ov_rect          = None
        self._grid_artists     = []
        self._meas_pts         = []
        self._meas_artists     = []
        self._meas_rubber   = self._meas_lbl_live = None
        self._meas_pending  = None
        self._meas_timer.stop()

        self.ax.cla()
        self.ax.set_axis_off()
        self.ax.set_aspect('equal', adjustable='datalim')
        self._default_lim = (xlim, ylim)
        self.ax.set_xlim(xlim)
        self.ax.set_ylim(ylim)

        self._redraw_photos()
        self._redraw_notes()
        self._request_tiles()
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.draw()

    # ── Ajout d'une trace GPS supplémentaire ─────────────────────────

    def add_track(self, gps: GPSData, color: str):
        """Ajoute une trace GPS à la vue courante sans réinitialiser la carte."""
        self._gps = gps
        self._gps_list.append(gps)

        # Dessine la nouvelle trace
        artist = self._add_track_artist_for(gps, color)
        self._track_artists.append(artist)

        # Marqueurs départ / arrivée dans la couleur de la trace
        s, = self.ax.plot(gps.xs[0],  gps.ys[0],  'o',
                          color=color, markersize=11, zorder=7,
                          markeredgecolor='white', markeredgewidth=2,
                          label=gps.filename)
        e, = self.ax.plot(gps.xs[-1], gps.ys[-1], 's',
                          color=color, markersize=10, zorder=7,
                          markeredgecolor='white', markeredgewidth=2)
        self._track_markers.append((s, e))
        self.ax.legend(loc='upper left', fontsize=9,
                       framealpha=0.85, fancybox=True)

        # Nouveau cursor dot + annotation pour cette trace (supprime les anciens)
        for attr in ('_cursor_dot', '_cursor_annot'):
            old = getattr(self, attr, None)
            if old is not None:
                try:
                    old.remove()
                except Exception:
                    pass
        self._cursor_dot, = self.ax.plot([], [], 'o',
            color=C_CURSOR, markersize=self._cursor_dot_size, zorder=10,
            markeredgecolor='white', markeredgewidth=1.5, visible=False)
        self._cursor_annot = self.ax.annotate(
            '', xy=(0, 0), xycoords='data',
            xytext=(14, 8), textcoords='offset points',
            color='white', fontsize=8.5,
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#1a2535',
                      edgecolor=C_CURSOR, alpha=0.92),
            zorder=12, visible=False)


        # Étend _default_lim pour englober la nouvelle trace
        mg = max(100, (gps.xs.max() - gps.xs.min()) * 0.18,
                       (gps.ys.max() - gps.ys.min()) * 0.18)
        if self._default_lim is not None:
            xl0, yl0 = self._default_lim
            new_xl = (min(xl0[0], gps.xs.min() - mg), max(xl0[1], gps.xs.max() + mg))
            new_yl = (min(yl0[0], gps.ys.min() - mg), max(yl0[1], gps.ys.max() + mg))
        else:
            new_xl = (gps.xs.min() - mg, gps.xs.max() + mg)
            new_yl = (gps.ys.min() - mg, gps.ys.max() + mg)
        self._default_lim = (new_xl, new_yl)

        self._request_tiles()
        if self._contours_enabled:
            self._contour_timer.start()
        self.draw_idle()
        self._playback_show(gps)

    def reset(self):
        """Remet le canvas dans l'état initial sans aucune trace ni photo."""
        self._contour_timer.stop()
        if self._contour_worker is not None:
            self._contour_worker.cancel()
            _retire_thread(self._contour_worker)
            self._contour_worker = None
        self._contour_sets   = []
        self._contour_labels = []
        self._tiles.request([])        # annule les tuiles en attente
        self._mosaic       = None
        self._tile_im_back = None
        self._tile_watchdog.stop()
        self._tile_draw_timer.stop()
        self._tile_timer.stop()
        self._pan_tile_timer.stop()
        self._meas_timer.stop()
        self._play_timer.stop()
        self._playing = False
        self._play_bar.setVisible(False)
        self._gps              = None
        self._gps_list         = []
        self._default_lim      = None
        self._track_artists    = []
        self._track_markers    = []
        self._track_filter_idx = None
        self._colorbar_ax   = None
        self._ov_ax         = None
        self._ov_rect       = None
        self._grid_artists  = []
        self._meas_pts      = []
        self._meas_artists  = []
        self._meas_rubber   = None
        self._meas_lbl_live = None
        self._meas_pending  = None
        self._measure_mode  = False
        self._photo_data    = []
        self._photo_artists = []
        self._note_data     = []
        self._note_artists  = []
        self._cursor_dot    = None
        self._cursor_annot  = None
        self._loading_text  = None
        self._error_text    = None
        self._live_line     = None
        self._live_dot      = None
        self._live_xs       = []
        self._live_ys       = []
        self.ax.cla()
        self.ax.set_axis_off()
        self._welcome()

    # ── Lecture automatique (playback) ──────────────────────────────

    def _build_play_bar(self) -> QWidget:
        """Crée la barre de lecture overlay (deux rangées : contrôles + scrubber)."""
        bar = QWidget(self)
        bar.setStyleSheet(
            'QWidget { background: rgba(20,30,45,210); border-top:1px solid #2c3e55; }'
            'QPushButton { background:#2c3e55; color:#cde; border:none; border-radius:4px;'
            '  padding:3px 10px; font-size:12px; }'
            'QPushButton:hover { background:#3d5a80; }'
            'QPushButton:checked { background:#1a6fbf; color:white; }'
            'QLabel { background:transparent; color:#9ab; font-size:11px; }'
            'QComboBox { background:#2c3e55; color:#cde; border:none; border-radius:4px;'
            '  padding:2px 6px; font-size:11px; }'
            'QSlider::groove:horizontal { height:4px; background:#2c3e55; border-radius:2px; }'
            'QSlider::sub-page:horizontal { background:#1a6fbf; border-radius:2px; }'
            'QSlider::handle:horizontal { width:12px; height:12px; margin:-4px 0;'
            '  background:#4fa3e0; border-radius:6px; }'
        )
        bar.setFixedHeight(56)

        outer = QVBoxLayout(bar)
        outer.setContentsMargins(8, 3, 8, 2)
        outer.setSpacing(2)

        # ── Rangée contrôles ─────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)

        self._play_btn_reset = QPushButton('«')
        self._play_btn_reset.setFixedWidth(30)
        self._play_btn_reset.setToolTip('Retour au début')
        self._play_btn_reset.clicked.connect(self._playback_reset)
        ctrl.addWidget(self._play_btn_reset)

        self._play_btn = QPushButton('▶  Suivre')
        self._play_btn.setFixedWidth(90)
        self._play_btn.setCheckable(True)
        self._play_btn.setToolTip('Lancer / mettre en pause la lecture automatique')
        self._play_btn.toggled.connect(self._playback_toggle)
        ctrl.addWidget(self._play_btn)

        self._play_lbl = QLabel('—')
        ctrl.addWidget(self._play_lbl, 1)

        ctrl.addWidget(QLabel('Vitesse :'))

        self._play_speed_combo = QComboBox()
        self._play_speed_combo.addItems(['×1', '×2', '×5', '×10'])
        self._play_speed_combo.setFixedWidth(60)
        self._play_speed_combo.setToolTip('Nombre de points sautés par tick (100 ms)')
        self._play_speed_combo.currentIndexChanged.connect(self._playback_set_speed)
        ctrl.addWidget(self._play_speed_combo)

        outer.addLayout(ctrl)

        # ── Rangée scrubber ──────────────────────────────────────────
        self._play_scrubber = QSlider(Qt.Horizontal)
        self._play_scrubber.setRange(0, 0)
        self._play_scrubber.setValue(0)
        self._play_scrubber.setToolTip('Glisser pour se positionner sur la trace')
        self._play_scrubber.sliderPressed.connect(self._on_scrub_press)
        self._play_scrubber.sliderMoved.connect(self._on_scrub_move)
        self._play_scrubber.sliderReleased.connect(self._on_scrub_release)
        outer.addWidget(self._play_scrubber)

        return bar

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_play_bar'):
            bh = self._play_bar.height()
            self._play_bar.setGeometry(0, self.height() - bh, self.width(), bh)

    def _playback_toggle(self, checked: bool):
        if checked:
            if self._gps is None:
                self._play_btn.setChecked(False)
                return
            if self._play_index >= self._gps.count - 1:
                self._play_index = 0
            self._playing = True
            self._play_btn.setText('‖  Pause')
            self._play_timer.start()
        else:
            self._playing = False
            self._play_btn.setText('▶  Suivre')
            self._play_timer.stop()

    def _playback_reset(self):
        self._play_timer.stop()
        self._playing = False
        self._play_btn.setChecked(False)
        self._play_btn.setText('▶  Suivre')
        self._play_index = 0
        if self._gps is not None:
            self._play_lbl.setText(f'point 1 / {self._gps.count}')
            self._play_scrubber.blockSignals(True)
            self._play_scrubber.setValue(0)
            self._play_scrubber.blockSignals(False)
            self.update_cursor(0)
            self.playback_index_changed.emit(0)

    def _playback_set_speed(self, idx: int):
        self._play_speed = [1, 2, 5, 10][idx]

    def _on_scrub_press(self):
        self._scrub_was_playing = self._playing
        if self._playing:
            self._play_timer.stop()

    def _on_scrub_move(self, value: int):
        if self._gps is None:
            return
        self._play_index = value
        self.update_cursor(value)
        self._play_lbl.setText(f'point {value + 1} / {self._gps.count}')
        self.playback_index_changed.emit(value)

    def _on_scrub_release(self):
        if self._scrub_was_playing:
            self._play_timer.start()

    def _playback_tick(self):
        if self._gps is None:
            self._playback_toggle(False)
            return
        self._play_index = min(self._play_index + self._play_speed,
                               self._gps.count - 1)
        self.update_cursor(self._play_index)
        self._play_lbl.setText(
            f'point {self._play_index + 1} / {self._gps.count}')
        self._play_scrubber.blockSignals(True)
        self._play_scrubber.setValue(self._play_index)
        self._play_scrubber.blockSignals(False)
        self.playback_index_changed.emit(self._play_index)
        self._autopan_to_cursor()
        if self._play_index >= self._gps.count - 1:
            self._play_btn.setChecked(False)

    def _autopan_to_cursor(self):
        """Recentre la carte si le curseur sort de la zone active."""
        if self._gps is None or self._play_index >= self._gps.count:
            return
        x = float(self._gps.xs[self._play_index])
        y = float(self._gps.ys[self._play_index])
        if self._autopan_margin_px > 0:
            disp = self.ax.transData.transform((x, y))
            m = self._autopan_margin_px
            outside = (disp[0] < m or disp[0] > self.width()  - m or
                       disp[1] < m or disp[1] > self.height() - m)
        else:
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            outside = not (xlim[0] < x < xlim[1] and ylim[0] < y < ylim[1])
        if outside:
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            half_x = (xlim[1] - xlim[0]) / 2
            half_y = (ylim[1] - ylim[0]) / 2
            self.ax.set_xlim(x - half_x, x + half_x)
            self.ax.set_ylim(y - half_y, y + half_y)
            self._reload_tiles()

    def _playback_show(self, gps: GPSData):
        """Affiche la barre et réinitialise l'état pour une nouvelle trace."""
        self._play_timer.stop()
        self._playing = False
        self._play_index = 0
        self._play_btn.setChecked(False)
        self._play_btn.setText('▶  Suivre')
        self._play_lbl.setText(f'point 1 / {gps.count}')
        self._play_scrubber.blockSignals(True)
        self._play_scrubber.setRange(0, gps.count - 1)
        self._play_scrubber.setValue(0)
        self._play_scrubber.blockSignals(False)
        self._play_bar.setVisible(True)
        bh = self._play_bar.height()
        self._play_bar.setGeometry(0, self.height() - bh, self.width(), bh)

    # ── Filtre de visibilité des traces ─────────────────────────────

    def set_track_filter(self, gps: 'GPSData | None'):
        """Affiche uniquement la trace gps sur la carte, ou toutes si None."""
        if gps is None:
            self._track_filter_idx = None
        else:
            try:
                self._track_filter_idx = self._gps_list.index(gps)
            except ValueError:
                self._track_filter_idx = None
        self._apply_track_filter()
        self.draw_idle()

    def _apply_track_filter(self):
        """Applique la visibilité des traces selon _track_filter_idx."""
        for i in range(len(self._track_artists)):
            vis = self._track_filter_idx is None or i == self._track_filter_idx
            self._track_artists[i].set_visible(vis)
            if i < len(self._track_markers):
                for m in self._track_markers[i]:
                    m.set_visible(vis)
        leg = self.ax.get_legend()
        if leg is not None:
            leg.set_visible(
                self._track_filter_idx is None and len(self._gps_list) > 1)

    # ── Curseur synchronisé avec les graphiques ──────────────────────

    def set_show_cursor_info(self, visible: bool):
        """Affiche ou masque l'annotation distance parcouru/restant."""
        self._show_cursor_info = visible
        if self._cursor_annot is not None:
            self._cursor_annot.set_visible(
                visible and self._cursor_dot is not None
                and self._cursor_dot.get_visible())
            self.draw_idle()

    # ── Setters paramétrage ──────────────────────────────────────────────

    def set_track_linewidth(self, width: float):
        self._track_linewidth = width
        for artist in self._track_artists:
            try:
                artist.set_linewidth(width)
            except AttributeError:
                pass
        self.draw_idle()

    def set_map_alpha(self, alpha: float):
        self._map_alpha = max(0.0, min(1.0, alpha))
        for im in (self._mosaic and self._mosaic['im'], self._tile_im_back):
            if im is not None:
                im.set_alpha(self._map_alpha)
        self.draw_idle()

    def set_photo_marker_size(self, zoom: float, cross: int):
        self._photo_zoom       = zoom
        self._photo_cross_size = cross

    def set_cursor_dot_size(self, size: int):
        self._cursor_dot_size = size
        if self._cursor_dot is not None:
            self._cursor_dot.set_markersize(size)
            self.draw_idle()

    def set_autopan_margin(self, margin_px: int):
        self._autopan_margin_px = margin_px

    def set_cursor_track(self, gps: GPSData):
        """Définit la trace dont les coordonnées sont utilisées pour le curseur."""
        self._gps = gps

    def update_cursor(self, index):
        if self._cursor_dot is None or self._gps is None:
            return
        if index is not None and 0 <= index < self._gps.count:
            x = float(self._gps.xs[index])
            y = float(self._gps.ys[index])
            self._cursor_dot.set_data([x], [y])
            self._cursor_dot.set_visible(True)
            if self._cursor_annot is not None:
                dist      = self._gps.distances[index]
                remaining = self._gps.total_dist - dist
                # Temps écoulé et heure GPS
                lines = [f'↑ {_fmt_dist(dist)}', f'↓ {_fmt_dist(remaining)}']
                el = self._gps.elapsed_times[index]
                if el is not None:
                    lines.append(f'Δ {_fmt_elapsed(el)}')
                pt = self._gps.points[index]
                t_raw = pt.get('time', '')
                if t_raw:
                    # "HH:MM:SS UTC" → "HH:MM"
                    parts = t_raw.replace(' UTC', '').split(':')
                    if len(parts) >= 2:
                        lines.append(f'◷ {parts[0]}:{parts[1]}')
                self._cursor_annot.xy = (x, y)
                self._cursor_annot.set_text('\n'.join(lines))
                self._cursor_annot.set_visible(self._show_cursor_info)
        else:
            self._cursor_dot.set_visible(False)
            if self._cursor_annot is not None:
                self._cursor_annot.set_visible(False)
        self.draw_idle()

    def center_on_point(self, index):
        """Recentre la carte sur le point GPS à cet index, en conservant le zoom."""
        if self._gps is None or index is None or not (0 <= index < self._gps.count):
            return
        x = float(self._gps.xs[index])
        y = float(self._gps.ys[index])
        xl = self.ax.get_xlim()
        yl = self.ax.get_ylim()
        hw = (xl[1] - xl[0]) / 2
        hh = (yl[1] - yl[0]) / 2
        self.ax.set_xlim(x - hw, x + hw)
        self.ax.set_ylim(y - hh, y + hh)
        self._request_tiles()
        self.draw_idle()

    # ── Courbes de niveau ────────────────────────────────────────────

    def toggle_contours(self, enabled: bool):
        """Active / désactive les courbes de niveau."""
        self._contours_enabled = enabled
        if enabled:
            if self._default_lim is not None:
                self._request_contours()
        else:
            self._contour_timer.stop()
            self._clear_contours()
            self.draw_idle()

    def _view_bounds_latlon(self):
        """Retourne (lat_min, lat_max, lon_min, lon_max) du viewport courant + 5 % de marge."""
        xl = self.ax.get_xlim()
        yl = self.ax.get_ylim()
        dx = (xl[1] - xl[0]) * 0.05
        dy = (yl[1] - yl[0]) * 0.05
        lat_min, lon_min = _webmerc_to_latlon(xl[0] - dx, yl[0] - dy)
        lat_max, lon_max = _webmerc_to_latlon(xl[1] + dx, yl[1] + dy)
        return lat_min, lat_max, lon_min, lon_max

    def _request_contours(self):
        """Lance le worker SRTM pour le viewport courant."""
        if self._default_lim is None:
            return
        if self._contour_worker is not None and self._contour_worker.isRunning():
            self._contour_worker.cancel()
            _retire_thread(self._contour_worker)
        self._clear_contours()
        self._contour_req += 1
        lat_min, lat_max, lon_min, lon_max = self._view_bounds_latlon()
        self._contour_worker = _ContourWorker(
            lat_min, lat_max, lon_min, lon_max, self._contour_req)
        self._contour_worker.contour_ready.connect(self._on_contours_ready)
        self._contour_worker.failed.connect(self._on_contours_failed)
        self.tile_loading.emit(True)
        self._contour_worker.start()

    def _on_contours_ready(self, lat_g, lon_g, elev_g, req_id: int):
        self.tile_loading.emit(False)
        if req_id == self._contour_req and self._contours_enabled:
            self._draw_contours(lat_g, lon_g, elev_g)

    def _on_contours_failed(self, msg: str):
        self.tile_loading.emit(False)

    def _clear_contours(self):
        """Efface tous les artists de courbes de niveau de l'axe."""
        for cs in self._contour_sets:
            try:
                cs.remove()
            except Exception:
                pass
        self._contour_sets = []
        for txt in self._contour_labels:
            try:
                txt.remove()
            except Exception:
                pass
        self._contour_labels = []

    def _draw_contours(self, lat_g, lon_g, elev_g):
        """Dessine les courbes de niveau sur la carte."""
        self._clear_contours()

        # Conversion lat/lon → Web Mercator (vectorisée)
        R   = 6378137.0
        x_g = np.radians(lon_g) * R
        y_g = R * np.log(np.tan(np.pi / 4 + np.radians(lat_g) / 2))

        # Intervalle adaptatif selon le dénivelé
        valid = elev_g[~np.isnan(elev_g)]
        if valid.size == 0:
            return
        e_min, e_max = float(valid.min()), float(valid.max())
        e_range = e_max - e_min
        if e_range < 150:
            interval = 25
        elif e_range < 500:
            interval = 50
        else:
            interval = 100

        first = int(np.floor(e_min / interval)) * interval
        last  = int(np.ceil(e_max  / interval)) * interval + interval
        minor_levels = list(range(first, last, interval))
        major_levels = [l for l in minor_levels if l % (interval * 5) == 0]
        if not minor_levels:
            return

        # Courbes mineures
        cs_minor = self.ax.contour(x_g, y_g, elev_g,
                                   levels=minor_levels,
                                   colors=['#8B6914'],
                                   linewidths=[0.4],
                                   alpha=0.55,
                                   zorder=4)
        self._contour_sets.append(cs_minor)

        # Courbes majeures + étiquettes
        if major_levels:
            cs_maj = self.ax.contour(x_g, y_g, elev_g,
                                     levels=major_levels,
                                     colors=['#5C3D0A'],
                                     linewidths=[0.9],
                                     alpha=0.75,
                                     zorder=4)
            self._contour_sets.append(cs_maj)
            self._contour_labels = self.ax.clabel(
                cs_maj, inline=True, fontsize=6, fmt='%d m',
                colors=['#3E2800'])

        self.draw_idle()

    def _on_key(self, event):
        if event.key == 'escape':
            if self._measure_mode:
                self.measure_mode_cancelled.emit()
            elif self._photo_mode:
                self.photo_mode_changed.emit(False)
            elif self._note_mode:
                self.note_mode_changed.emit(False)
        elif event.key == 'p':
            self.photo_mode_changed.emit(not self._photo_mode)
        elif event.key == 'n':
            self.note_mode_changed.emit(not self._note_mode)
        elif event.key in ('v', 'w', 'x'):
            self._handle_eye_key(event.key)

    # ══════════════════════════════════════════════════════════════════
    #  Réception GPS en temps réel (LoRa Live)
    # ══════════════════════════════════════════════════════════════════

    def start_live_track(self, color: str = '#e67e22'):
        """Prépare l'overlay live. Les artistes sont créés au premier point si la carte est vide."""
        self._stop_live_artists()
        self._live_color = color
        self._live_xs    = []
        self._live_ys    = []

        if self._default_lim is not None:
            # Carte déjà visible : ajoute la ligne et le point immédiatement
            self._live_line, = self.ax.plot(
                [], [], color=color, linewidth=2.5, zorder=5,
                solid_capstyle='round', solid_joinstyle='round',
                label='◎ LoRa Live')
            self._live_dot, = self.ax.plot(
                [], [], 'o', color=color, markersize=13, zorder=10,
                markeredgecolor='white', markeredgewidth=2)
            self.ax.legend(loc='upper left', fontsize=9,
                           framealpha=0.85, fancybox=True)
            self.draw_idle()
        else:
            # Carte vide : les artistes seront créés dans _init_live_map
            self._live_line = None
            self._live_dot  = None

    def append_live_point(self, x_m: float, y_m: float):
        """Ajoute un point GPS reçu en temps réel et met à jour la carte.

        Appelé depuis le thread principal via signal Qt.
        """
        self._live_xs.append(x_m)
        self._live_ys.append(y_m)

        # Initialise la vue au premier point si la carte est encore vide
        if self._live_line is None:
            self._init_live_map(x_m, y_m)

        self._live_line.set_data(self._live_xs, self._live_ys)
        self._live_dot.set_data([x_m], [y_m])

        # Auto-pan : recentre si le point sort de la zone centrale (70 % de la vue)
        xl, yl   = self.ax.get_xlim(), self.ax.get_ylim()
        margin_x = (xl[1] - xl[0]) * 0.15
        margin_y = (yl[1] - yl[0]) * 0.15
        if (x_m < xl[0] + margin_x or x_m > xl[1] - margin_x or
                y_m < yl[0] + margin_y or y_m > yl[1] - margin_y):
            hw = (xl[1] - xl[0]) / 2
            hh = (yl[1] - yl[0]) / 2
            self.ax.set_xlim(x_m - hw, x_m + hw)
            self.ax.set_ylim(y_m - hh, y_m + hh)
            self._tile_timer.start()

        self.draw_idle()

    def _init_live_map(self, x_m: float, y_m: float):
        """Configure la vue centrée sur le premier point live (carte était vide)."""
        margin = 500  # 500 m de rayon initial
        xlim = (x_m - margin, x_m + margin)
        ylim = (y_m - margin, y_m + margin)
        self._default_lim = (xlim, ylim)

        self.ax.cla()
        self.ax.set_axis_off()
        self.ax.set_aspect('equal', adjustable='datalim')
        self.ax.set_xlim(xlim)
        self.ax.set_ylim(ylim)
        self._loading_text = None
        self._error_text   = None
        self._cursor_dot   = None
        self._cursor_annot = None

        self._live_line, = self.ax.plot(
            [], [], color=self._live_color, linewidth=2.5, zorder=5,
            solid_capstyle='round', solid_joinstyle='round',
            label='◎ LoRa Live')
        self._live_dot, = self.ax.plot(
            [], [], 'o', color=self._live_color, markersize=13, zorder=10,
            markeredgecolor='white', markeredgewidth=2)
        self.ax.legend(loc='upper left', fontsize=9,
                       framealpha=0.85, fancybox=True)

        # Redessine les éventuelles annotations déjà chargées
        self._redraw_photos()
        self._redraw_notes()

        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self._request_tiles()

    def stop_live_track(self):
        """Retire les artistes live de la carte (les traces chargées restent visibles)."""
        self._stop_live_artists()
        self._live_xs = []
        self._live_ys = []
        self.draw_idle()

    def _stop_live_artists(self):
        """Supprime proprement les artistes matplotlib de la trace live."""
        for attr in ('_live_line', '_live_dot'):
            art = getattr(self, attr, None)
            if art is not None:
                try:
                    art.remove()
                except Exception:
                    pass
                setattr(self, attr, None)
