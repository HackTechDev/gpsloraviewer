"""
map_canvas.py — MapCanvas, _TileCache, _TileWorker, _douglas_peucker_mask,
                constantes visuelles, cache de tuiles contextily.
"""

import math
from collections import OrderedDict
from pathlib import Path

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
from PIL import Image as PilImage
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QSizePolicy, QApplication,
                              QWidget, QHBoxLayout, QPushButton,
                              QLabel, QComboBox)

from gps_nmea import GPSData, to_webmerc, _webmerc_to_latlon, WEB_MERC_R

# ── Cache persistant de tuiles ────────────────────────────────────────
# Par défaut contextily stocke les tuiles dans un dossier temporaire
# supprimé à la fermeture. On le redirige vers ~/.cache/gps_viewer/tiles
# pour qu'elles soient réutilisées entre les sessions.
_TILE_CACHE_DIR = Path.home() / '.cache' / 'gps_viewer' / 'tiles'
_TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
cx.set_cache_dir(str(_TILE_CACHE_DIR))


def _fmt_dist(d: float) -> str:
    """Formate une distance : km si ≥ 1 000 m, sinon mètres."""
    return f'{d / 1000:.1f} km' if d >= 1000 else f'{d:.0f} m'


def _cache_size_mb() -> float:
    """Retourne la taille du cache de tuiles en Mo."""
    return sum(f.stat().st_size for f in _TILE_CACHE_DIR.rglob('*') if f.is_file()) / 1_048_576


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
#  Simplification Douglas-Peucker (itératif, thread-safe)
# ══════════════════════════════════════════════════════════════════════

def _douglas_peucker_mask(xs: np.ndarray, ys: np.ndarray,
                          epsilon: float) -> np.ndarray:
    """Retourne un masque booléen : True = point conservé."""
    n = len(xs)
    if n <= 2:
        return np.ones(n, dtype=bool)
    mask = np.zeros(n, dtype=bool)
    mask[0] = mask[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end - start <= 1:
            continue
        dx = xs[end] - xs[start]
        dy = ys[end] - ys[start]
        line_len = math.hypot(dx, dy)
        if line_len < 1e-10:
            continue
        dists = np.abs(
            (ys[start:end + 1] - ys[start]) * dx
            - (xs[start:end + 1] - xs[start]) * dy
        ) / line_len
        local = int(np.argmax(dists[1:-1]))
        if dists[1 + local] > epsilon:
            abs_idx = start + 1 + local
            mask[abs_idx] = True
            stack.append((start, abs_idx))
            stack.append((abs_idx, end))
    return mask


# ══════════════════════════════════════════════════════════════════════
#  Cache LRU en mémoire (N dernières vues de carte)
# ══════════════════════════════════════════════════════════════════════

class _TileCache:
    """LRU cache pour les images de tuiles : rend les aller-retours instantanés."""

    def __init__(self, maxsize: int = 20):
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize

    def get(self, key):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key, value):
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def __len__(self):
        return len(self._cache)


# ══════════════════════════════════════════════════════════════════════
#  Thread de chargement asynchrone des tuiles
# ══════════════════════════════════════════════════════════════════════

class _TileWorker(QThread):
    """Charge les tuiles OSM en arrière-plan sans bloquer l'interface."""
    tiles_ready = pyqtSignal(object, object, object)  # img, ext, cache_key
    failed      = pyqtSignal(str)

    def __init__(self, xl, yl, zoom: int, source, headers: dict, cache_key):
        super().__init__()
        self._xl        = xl
        self._yl        = yl
        self._zoom      = zoom
        self._source    = source
        self._headers   = headers
        self._cache_key = cache_key
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        try:
            # Figure sans canvas Qt : opérations purement data, thread-safe.
            # cx.add_basemap ne déclenche aucun rendu GUI sur ce Figure nu.
            tmp_fig = Figure()
            tmp_ax  = tmp_fig.add_axes([0, 0, 1, 1])
            tmp_ax.set_xlim(self._xl)
            tmp_ax.set_ylim(self._yl)
            cx.add_basemap(tmp_ax, crs='EPSG:3857',
                           source=self._source,
                           zoom=self._zoom,
                           attribution_size=0,
                           headers=self._headers or None)
            if self._cancelled:
                return
            if tmp_ax.images:
                im  = tmp_ax.images[0]
                img = np.array(im.get_array())
                ext = list(im.get_extent())
                self.tiles_ready.emit(img, ext, self._cache_key)
            else:
                self.failed.emit('Aucune tuile retournée')
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


# ══════════════════════════════════════════════════════════════════════
#  Thread de calcul des courbes de niveau (SRTM)
# ══════════════════════════════════════════════════════════════════════

class _ContourWorker(QThread):
    """Télécharge les données SRTM et calcule la grille d'altitude en arrière-plan."""
    contour_ready = pyqtSignal(object, object, object, int)  # lat_g, lon_g, elev_g, req_id
    failed        = pyqtSignal(str)

    def __init__(self, lat_min, lat_max, lon_min, lon_max, req_id: int):
        super().__init__()
        self._lat_min   = lat_min
        self._lat_max   = lat_max
        self._lon_min   = lon_min
        self._lon_max   = lon_max
        self._req_id    = req_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            import srtm
        except ImportError:
            self.failed.emit("srtm.py non installé — pip install srtm.py")
            return
        try:
            data  = srtm.get_data()
            n_lat, n_lon = 80, 80
            lats  = np.linspace(self._lat_min, self._lat_max, n_lat)
            lons  = np.linspace(self._lon_min, self._lon_max, n_lon)
            elev  = np.full((n_lat, n_lon), np.nan)
            for i, lat in enumerate(lats):
                if self._cancelled:
                    return
                for j, lon in enumerate(lons):
                    e = data.get_elevation(lat, lon)
                    if e is not None:
                        elev[i, j] = float(e)
            lon_g, lat_g = np.meshgrid(lons, lats)
            if not self._cancelled:
                self.contour_ready.emit(lat_g, lon_g, elev, self._req_id)
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


# ══════════════════════════════════════════════════════════════════════
#  Canvas Carte  (matplotlib + contextily OSM)
# ══════════════════════════════════════════════════════════════════════

class MapCanvas(FigureCanvas):
    tile_loading           = pyqtSignal(bool)   # True = début, False = fin
    measure_updated        = pyqtSignal(str)    # message status bar
    measure_mode_cancelled = pyqtSignal()       # Échap appuyé en mode mesure
    photo_requested        = pyqtSignal(float, float)  # x_m, y_m Web Mercator
    photo_mode_changed     = pyqtSignal(bool)   # basculement mode photo
    photo_clicked          = pyqtSignal(int)    # index dans _photo_data
    photo_eye_changed      = pyqtSignal(int)    # angle œil modifié → sauvegarder
    playback_index_changed = pyqtSignal(int)    # lecture automatique : index courant

    def __init__(self):
        self.fig = Figure(facecolor='#2b2b2b')
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_axis_off()
        self._cursor_dot   = None
        self._cursor_annot = None   # annotation distance parcouru/restant
        self._gps: GPSData | None = None
        self._gps_list: list      = []
        self._default_lim = None   # (xlim, ylim) pour reset
        self._tile_source   = cx.providers.OpenStreetMap.Mapnik
        self._tile_headers  = {}   # headers HTTP pour la source active

        # ── Cache LRU en mémoire ─────────────────────────────────────
        self._tile_cache  = _TileCache(maxsize=20)
        self._tile_worker: _TileWorker | None = None
        self._pending_key = None   # clé de la dernière requête en cours

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

        # ── État pan ────────────────────────────────────────────────
        self._pan_xy   = None   # position pixel au début du drag
        self._pan_lims = None   # (xlim, ylim) au début du drag

        # ── Courbes de niveau ────────────────────────────────────────
        self._contours_enabled  = False
        self._contour_worker: _ContourWorker | None = None
        self._contour_sets      = []   # ContourSet objects (cs.remove() matplotlib 3.8+)
        self._contour_labels    = []   # Text objects des étiquettes (remove séparé)
        self._contour_req       = 0    # compteur de requête — invalide les résultats périmés

        # ── Timer rechargement tuiles (débounce 450 ms) ─────────────
        self._tile_timer = QTimer(singleShot=True, interval=450)
        self._tile_timer.timeout.connect(self._reload_tiles)

        # ── Timer courbes de niveau (débounce 900 ms) ────────────────
        self._contour_timer = QTimer(singleShot=True, interval=900)
        self._contour_timer.timeout.connect(self._request_contours)

        # ── Lecture automatique (playback) ───────────────────────────
        self._play_index  = 0
        self._play_speed  = 1    # points sautés par tick
        self._playing     = False
        self._play_timer  = QTimer(self, interval=100)
        self._play_timer.timeout.connect(self._playback_tick)
        self._play_bar    = self._build_play_bar()
        self._play_bar.setVisible(False)

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
            color=C_CURSOR, markersize=12, zorder=10,
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
                xs, ys, color=color, linewidth=2.5, zorder=5,
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
                              linewidth=2.5, zorder=5,
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
        if self._default_lim is not None:
            self._reload_tiles()

    # ── Zoom adaptatif ───────────────────────────────────────────────

    def _compute_zoom(self) -> int:
        """Calcule le niveau de zoom OSM optimal pour la vue courante."""
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        span_m = max(xl[1] - xl[0], yl[1] - yl[0])
        if span_m <= 0:
            return 12
        # Circonférence équatoriale en Web Mercator ≈ 40 075 016 m ;
        # +2 pour avoir ~4–8 tuiles visibles selon l'étendue.
        z = int(math.log2(max(1, 40_075_016 / span_m))) + 2
        return max(2, min(z, 18))

    def _cache_key(self, zoom: int):
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        r = 500  # grille 500 m : tolère les micro-décalages de pan
        src = str(self._tile_source)[:100]
        return (round(xl[0]/r), round(xl[1]/r),
                round(yl[0]/r), round(yl[1]/r),
                zoom, src)

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
        """Lance le chargement des tuiles (cache LRU → thread si miss)."""
        if self._default_lim is None:
            return
        zoom = self._compute_zoom()
        key  = self._cache_key(zoom)

        # Annule le worker précédent s'il tourne encore
        if self._tile_worker is not None and self._tile_worker.isRunning():
            self._tile_worker.cancel()

        cached = self._tile_cache.get(key)
        if cached is not None:
            self._apply_tiles(*cached)
            self._update_overview()
            if self._grid_visible:
                self._draw_grid()
            return

        self._pending_key  = key
        self._show_loading()
        self.tile_loading.emit(True)
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        self._tile_worker = _TileWorker(
            xl, yl, zoom, self._tile_source, self._tile_headers, key)
        self._tile_worker.tiles_ready.connect(self._on_tiles_ready)
        self._tile_worker.failed.connect(self._on_tiles_failed)
        self._tile_worker.start()

    def _apply_tiles(self, img, ext):
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        for im in list(self.ax.images):
            im.remove()
        self.ax.imshow(img, extent=ext, interpolation='bilinear', zorder=0)
        self.ax.set_xlim(xl)
        self.ax.set_ylim(yl)
        self.draw_idle()

    def _on_tiles_ready(self, img, ext, key):
        if key != self._pending_key:
            return
        self._tile_cache.put(key, (img, ext))
        self._apply_tiles(img, ext)
        self._hide_loading()
        self.tile_loading.emit(False)
        self._update_overview()
        if self._grid_visible:
            self._draw_grid()

    def _on_tiles_failed(self, msg: str):
        self._hide_loading()
        self.tile_loading.emit(False)
        self.ax.set_facecolor('#d9e8f5')
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        self.ax.text(0.5, 0.02, f'Tuiles indisponibles : {msg}',
                     transform=self.ax.transAxes, ha='center',
                     fontsize=8, color='#c00', zorder=20)
        self.ax.set_xlim(xl)
        self.ax.set_ylim(yl)
        self.draw_idle()

    def _show_loading(self):
        if self._loading_text is None:
            self._loading_text = self.ax.text(
                0.5, 0.02, 'Chargement des tuiles…',
                transform=self.ax.transAxes, ha='center', va='bottom',
                color='#555', fontsize=9, fontfamily='monospace',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.75),
                zorder=20)
        else:
            self._loading_text.set_visible(True)
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
        self._tile_timer.start()   # recharge les tuiles 450 ms après le dernier scroll

    # ── Pan (clic gauche + glisser) ──────────────────────────────────

    def _on_press(self, event):
        if self._photo_mode:
            if (event.button == 1 and event.inaxes == self.ax
                    and event.xdata is not None
                    and not getattr(event, 'dblclick', False)):
                self.photo_requested.emit(event.xdata, event.ydata)
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
            color=C_CURSOR, markersize=12, zorder=10,
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
            self._contour_worker = None
        self._contour_sets   = []
        self._contour_labels = []
        if self._tile_worker is not None:
            self._tile_worker.cancel()
            self._tile_worker = None
        self._tile_timer.stop()
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
        self._cursor_dot    = None
        self._cursor_annot  = None
        self._loading_text  = None
        self.ax.cla()
        self.ax.set_axis_off()
        self._welcome()

    # ── Lecture automatique (playback) ──────────────────────────────

    def _build_play_bar(self) -> QWidget:
        """Crée la barre de lecture overlay."""
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
        )
        bar.setFixedHeight(36)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(6)

        self._play_btn_reset = QPushButton('⏮')
        self._play_btn_reset.setFixedWidth(30)
        self._play_btn_reset.setToolTip('Retour au début')
        self._play_btn_reset.clicked.connect(self._playback_reset)
        layout.addWidget(self._play_btn_reset)

        self._play_btn = QPushButton('▶  Suivre')
        self._play_btn.setFixedWidth(90)
        self._play_btn.setCheckable(True)
        self._play_btn.setToolTip('Lancer / mettre en pause la lecture automatique')
        self._play_btn.toggled.connect(self._playback_toggle)
        layout.addWidget(self._play_btn)

        self._play_lbl = QLabel('—')
        layout.addWidget(self._play_lbl, 1)

        layout.addWidget(QLabel('Vitesse :'))

        self._play_speed_combo = QComboBox()
        self._play_speed_combo.addItems(['×1', '×2', '×5', '×10'])
        self._play_speed_combo.setFixedWidth(60)
        self._play_speed_combo.setToolTip('Nombre de points sautés par tick (100 ms)')
        self._play_speed_combo.currentIndexChanged.connect(self._playback_set_speed)
        layout.addWidget(self._play_speed_combo)

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
            self._play_btn.setText('⏸  Pause')
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
            self.update_cursor(0)
            self.playback_index_changed.emit(0)

    def _playback_set_speed(self, idx: int):
        self._play_speed = [1, 2, 5, 10][idx]

    def _playback_tick(self):
        if self._gps is None:
            self._playback_toggle(False)
            return
        self._play_index = min(self._play_index + self._play_speed,
                               self._gps.count - 1)
        self.update_cursor(self._play_index)
        self._play_lbl.setText(
            f'point {self._play_index + 1} / {self._gps.count}')
        self.playback_index_changed.emit(self._play_index)
        self._autopan_to_cursor()
        if self._play_index >= self._gps.count - 1:
            self._play_btn.setChecked(False)

    def _autopan_to_cursor(self):
        """Recentre la carte si le curseur sort de la vue."""
        if self._gps is None or self._play_index >= self._gps.count:
            return
        x = float(self._gps.xs[self._play_index])
        y = float(self._gps.ys[self._play_index])
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        if not (xlim[0] < x < xlim[1] and ylim[0] < y < ylim[1]):
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
                self._cursor_annot.xy = (x, y)
                self._cursor_annot.set_text(
                    f'↑ {_fmt_dist(dist)}\n↓ {_fmt_dist(remaining)}')
                self._cursor_annot.set_visible(True)
        else:
            self._cursor_dot.set_visible(False)
            if self._cursor_annot is not None:
                self._cursor_annot.set_visible(False)
        self.draw_idle()

    # ── Mesure de distance ───────────────────────────────────────────

    def set_measure_mode(self, active: bool):
        self._measure_mode = active
        if active:
            self._clear_measure()
            self.setCursor(Qt.CrossCursor)
            self.measure_updated.emit(
                'Mesure : cliquez pour placer le point A  •  Échap pour annuler')
        else:
            self._clear_measure()
            self.setCursor(Qt.OpenHandCursor)
            self.measure_updated.emit('')

    def _meas_commit_pending(self):
        """Appelé 200 ms après un clic simple : pose le point."""
        if self._meas_pending is not None:
            x, y = self._meas_pending
            self._meas_pending = None
            self._meas_add_point(x, y)

    def _meas_finalize(self):
        """Double-clic : fige la mesure en cours, prêt pour une nouvelle."""
        for a in (self._meas_rubber, self._meas_lbl_live):
            if a is not None:
                try:
                    a.remove()
                except Exception:
                    pass
        self._meas_rubber = self._meas_lbl_live = None

        n = len(self._meas_pts)
        if n >= 2:
            total_m = sum(
                self._meas_dist_m(self._meas_pts[i][0], self._meas_pts[i][1],
                                  self._meas_pts[i+1][0], self._meas_pts[i+1][1])
                for i in range(n - 1))
            msg = (f'Mesure figée — Total : {self._fmt_dist(total_m)}  •  '
                   f'Cliquez pour une nouvelle mesure  •  Échap pour tout effacer')
        else:
            msg = ('Cliquez pour démarrer une mesure  •  Échap pour annuler')

        self._meas_pts = []
        self.measure_updated.emit(msg)
        self.draw_idle()

    def _clear_measure(self):
        self._meas_timer.stop()
        self._meas_pending = None
        for a in self._meas_artists:
            try:
                a.remove()
            except Exception:
                pass
        self._meas_artists = []
        self._meas_pts     = []
        for a in (self._meas_rubber, self._meas_lbl_live):
            if a is not None:
                try:
                    a.remove()
                except Exception:
                    pass
        self._meas_rubber = self._meas_lbl_live = None
        self.draw_idle()

    def _meas_add_point(self, x: float, y: float):
        """Place un nouveau point de mesure et fige le segment précédent."""
        # Supprime le rubber-band live
        for a in (self._meas_rubber, self._meas_lbl_live):
            if a is not None:
                try:
                    a.remove()
                except Exception:
                    pass
        self._meas_rubber = self._meas_lbl_live = None

        # Marqueur du nouveau point
        dot, = self.ax.plot(x, y, 'o', color='#e67e22', markersize=9,
                            zorder=9, markeredgecolor='white',
                            markeredgewidth=1.5)
        self._meas_artists.append(dot)

        if self._meas_pts:
            x0, y0 = self._meas_pts[-1]
            seg_m  = self._meas_dist_m(x0, y0, x, y)
            total_m = sum(
                self._meas_dist_m(self._meas_pts[i][0], self._meas_pts[i][1],
                                  self._meas_pts[i+1][0], self._meas_pts[i+1][1])
                for i in range(len(self._meas_pts) - 1)
            ) + seg_m

            seg_line, = self.ax.plot(
                [x0, x], [y0, y], color='#e67e22',
                linewidth=1.8, linestyle='--', zorder=8)
            self._meas_artists.append(seg_line)

            txt = self._fmt_dist(seg_m)
            if len(self._meas_pts) >= 2:
                txt += f'\n∑ {self._fmt_dist(total_m)}'
            lbl = self.ax.text(
                (x0 + x) / 2, (y0 + y) / 2, txt,
                fontsize=8, color='#222', zorder=10,
                ha='center', va='center',
                bbox=dict(boxstyle='round,pad=0.28', facecolor='#fff8dc',
                          alpha=0.92, edgecolor='#e67e22', linewidth=0.8))
            self._meas_artists.append(lbl)

            self.measure_updated.emit(
                f'Segment : {self._fmt_dist(seg_m)}  •  '
                f'Total : {self._fmt_dist(total_m)}  •  '
                f'Cliquez pour continuer  •  Échap pour annuler')
        else:
            self.measure_updated.emit(
                f'Point A posé  •  Cliquez pour placer le point B  •  '
                f'Échap pour annuler')

        self._meas_pts.append((x, y))
        self.draw_idle()

    def _meas_update_rubber(self, x: float, y: float):
        """Met à jour la ligne rubber-band et le label de distance live."""
        x0, y0 = self._meas_pts[-1]
        dist_m = self._meas_dist_m(x0, y0, x, y)

        for a in (self._meas_rubber, self._meas_lbl_live):
            if a is not None:
                try:
                    a.remove()
                except Exception:
                    pass

        self._meas_rubber, = self.ax.plot(
            [x0, x], [y0, y], color='#e67e22',
            linewidth=1.3, linestyle=':', zorder=8, alpha=0.75)
        self._meas_lbl_live = self.ax.text(
            x, y, f'  {self._fmt_dist(dist_m)}',
            fontsize=8, color='#c0392b', zorder=10,
            ha='left', va='bottom',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                      alpha=0.78, edgecolor='none'))
        self.draw_idle()

    # ── Mode annotation photo ────────────────────────────────────────

    def set_photo_mode(self, active: bool):
        self._photo_mode = active
        if active:
            self.setCursor(Qt.CrossCursor)
        elif not self._measure_mode:
            self.setCursor(Qt.OpenHandCursor)

    def load_photo_data(self, entries: list):
        """Charge des annotations photo sauvegardées sans les dessiner."""
        self._photo_data    = entries
        self._photo_artists = []

    def add_photo_annotation(self, x_m: float, y_m: float,
                              lat: float, lon: float,
                              orig_path: str, thumb_path: str):
        """Ajoute une annotation photo à la carte et la mémorise."""
        entry = {
            'x_m': x_m, 'y_m': y_m,
            'lat': lat,  'lon': lon,
            'orig_path': orig_path,
            'thumb_path': thumb_path,
        }
        self._photo_data.append(entry)
        artists = self._draw_photo_annotation(x_m, y_m, thumb_path)
        self._photo_artists.append(artists)
        self.draw_idle()

    def _draw_photo_annotation(self, x_m: float, y_m: float,
                                thumb_path: str) -> list:
        """Dessine la croix et la miniature ; retourne la liste d'artistes."""
        artists = []
        cross, = self.ax.plot(
            x_m, y_m, '+', color='#e74c3c',
            markersize=16, markeredgewidth=2.5, zorder=12)
        cross.pickradius = 12   # zone de clic élargie pour la croix
        artists.append(cross)
        try:
            img_arr  = np.array(PilImage.open(thumb_path).convert('RGB'))
            imgbox   = OffsetImage(img_arr, zoom=0.8)
            ab = AnnotationBbox(
                imgbox, (x_m, y_m),
                xycoords='data',
                xybox=(0, 55),
                boxcoords='offset points',
                frameon=True,
                pad=0.3,
                arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=1.5),
                bboxprops=dict(edgecolor='#e74c3c', linewidth=1.5,
                               facecolor='white', alpha=0.92),
                zorder=13)
            self.ax.add_artist(ab)
            artists.append(ab)
        except Exception:
            pass
        return artists

    def _redraw_photos(self):
        """Redessine toutes les annotations photo après un ax.cla()."""
        self._photo_artists = []
        for i, entry in enumerate(self._photo_data):
            artists = self._draw_photo_annotation(
                entry['x_m'], entry['y_m'], entry['thumb_path'])
            self._photo_artists.append(artists)
            if entry.get('angle') is not None:
                self._draw_eye(i)

    def _eye_radius(self) -> float:
        """Rayon du cercle-œil en unités données : 3.5 % de la largeur de vue."""
        xl = self.ax.get_xlim()
        return (xl[1] - xl[0]) * 0.035

    def _draw_eye(self, idx: int):
        """Dessine (ou redessine) l'indicateur de direction pour la photo idx."""
        from matplotlib.patches import Circle as MplCircle
        # Supprime les artistes-œil existants (indices ≥ 2)
        if idx < len(self._photo_artists):
            for art in self._photo_artists[idx][2:]:
                try:
                    art.remove()
                except Exception:
                    pass
            self._photo_artists[idx] = self._photo_artists[idx][:2]

        entry = self._photo_data[idx]
        angle = entry.get('angle')
        if angle is None:
            return

        x_m, y_m   = entry['x_m'], entry['y_m']
        R           = self._eye_radius()
        theta       = math.radians(angle)
        eye_artists = []

        # ── Anneau extérieur ─────────────────────────────────────────
        ring = MplCircle((x_m, y_m), R,
                         fill=False, edgecolor='#3498db',
                         linewidth=1.6, linestyle='--', zorder=11,
                         transform=self.ax.transData)
        self.ax.add_patch(ring)
        eye_artists.append(ring)

        # ── Position de l'œil sur l'anneau ───────────────────────────
        ex, ey = x_m + R * math.cos(theta), y_m + R * math.sin(theta)
        r_eye  = R * 0.22

        # Blanc de l'œil
        sclera = MplCircle((ex, ey), r_eye,
                           facecolor='white', edgecolor='#2c3e50',
                           linewidth=1.4, zorder=12,
                           transform=self.ax.transData)
        self.ax.add_patch(sclera)
        eye_artists.append(sclera)

        # Pupille (décalée vers la croix)
        dist = math.hypot(x_m - ex, y_m - ey)
        if dist > 0:
            px = ex + (x_m - ex) / dist * r_eye * 0.42
            py = ey + (y_m - ey) / dist * r_eye * 0.42
        else:
            px, py = ex, ey
        pupil = MplCircle((px, py), r_eye * 0.44,
                          facecolor='#1a252f', edgecolor='none',
                          zorder=13,
                          transform=self.ax.transData)
        self.ax.add_patch(pupil)
        eye_artists.append(pupil)

        # Reflet (petit cercle blanc dans la pupille)
        reflet = MplCircle((px + r_eye * 0.14, py + r_eye * 0.14),
                            r_eye * 0.13,
                            facecolor='white', edgecolor='none',
                            zorder=14,
                            transform=self.ax.transData)
        self.ax.add_patch(reflet)
        eye_artists.append(reflet)

        if idx < len(self._photo_artists):
            self._photo_artists[idx].extend(eye_artists)

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

    def reload_photo_annotations(self):
        """Supprime les artistes photo existants puis redessine depuis _photo_data."""
        for artists in self._photo_artists:
            for art in artists:
                try:
                    art.remove()
                except Exception:
                    pass
        self._redraw_photos()
        self.draw_idle()

    def _find_photo_at(self, event, radius_px: int = 48,
                       check_thumbnail: bool = False) -> 'int | None':
        """Retourne l'index de la photo sous le curseur.

        Vérifie :
          - la distance en pixels à la croix (≤ radius_px)
          - si check_thumbnail=True, la boîte de la miniature via contains()
            (fiable uniquement lors d'un clic, pas d'un mouvement)
        """
        if not self._photo_data or event.x is None or event.y is None:
            return None
        for i, entry in enumerate(self._photo_data):
            # ── Proximité de la croix ────────────────────────────────
            try:
                dp = self.ax.transData.transform((entry['x_m'], entry['y_m']))
                if math.hypot(event.x - dp[0], event.y - dp[1]) <= radius_px:
                    return i
            except Exception:
                pass
            # ── Miniature (AnnotationBbox) ───────────────────────────
            if check_thumbnail:
                artists = self._photo_artists[i] if i < len(self._photo_artists) else []
                if len(artists) >= 2:
                    try:
                        hit, _ = artists[1].contains(event)
                        if hit:
                            return i
                    except Exception:
                        pass
        return None

    def _on_key(self, event):
        if event.key == 'escape':
            if self._measure_mode:
                self.measure_mode_cancelled.emit()
            elif self._photo_mode:
                self.photo_mode_changed.emit(False)
        elif event.key == 'p':
            self.photo_mode_changed.emit(not self._photo_mode)
        elif event.key in ('v', 'w', 'x'):
            self._handle_eye_key(event.key)

    def _handle_eye_key(self, key: str):
        idx = self._hovered_photo_idx
        if idx is None or idx >= len(self._photo_data):
            return
        entry = self._photo_data[idx]
        if key == 'v':
            if entry.get('angle') is None:
                entry['angle'] = 90.0   # 12 h : l'œil regarde vers le bas
            else:
                entry['angle'] = None   # masque l'œil
        elif key == 'w':
            if entry.get('angle') is not None:
                entry['angle'] = (entry['angle'] + 15) % 360
            else:
                return
        elif key == 'x':
            if entry.get('angle') is not None:
                entry['angle'] = (entry['angle'] - 15) % 360
            else:
                return
        self._draw_eye(idx)
        self.draw_idle()
        self.photo_eye_changed.emit(idx)

    @staticmethod
    def _meas_dist_m(x0: float, y0: float, x1: float, y1: float) -> float:
        lat0, lon0 = _webmerc_to_latlon(x0, y0)
        lat1, lon1 = _webmerc_to_latlon(x1, y1)
        from gps_nmea import haversine_m
        return haversine_m(lat0, lon0, lat1, lon1)

    @staticmethod
    def _fmt_dist(m: float) -> str:
        if m < 1000:
            return f'{m:.0f} m'
        return f'{m / 1000:.3f} km'
