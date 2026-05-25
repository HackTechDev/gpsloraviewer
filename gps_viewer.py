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
from collections import OrderedDict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.ticker as mticker
import contextily as cx

# ── Cache persistant de tuiles ────────────────────────────────────────
# Par défaut contextily stocke les tuiles dans un dossier temporaire
# supprimé à la fermeture. On le redirige vers ~/.cache/gps_viewer/tiles
# pour qu'elles soient réutilisées entre les sessions.
_TILE_CACHE_DIR = Path.home() / '.cache' / 'gps_viewer' / 'tiles'
_TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
cx.set_cache_dir(str(_TILE_CACHE_DIR))


def _cache_size_mb() -> float:
    """Retourne la taille du cache de tuiles en Mo."""
    return sum(f.stat().st_size for f in _TILE_CACHE_DIR.rglob('*') if f.is_file()) / 1_048_576

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel, QAction,
    QFileDialog, QStatusBar, QMessageBox,
    QFrame, QToolBar, QSizePolicy,
    QToolButton, QMenu,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QSpinBox, QLineEdit, QGridLayout,
)
from PyQt5.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont

# ── Couleurs ─────────────────────────────────────────────────────────
C_TRACK   = '#1a6fbf'
C_ALT     = '#1a6fbf'
C_SPD     = '#27ae60'
C_CURSOR  = '#e74c3c'
C_START   = '#2ecc71'
C_END     = '#e74c3c'

WEB_MERC_R = 6_378_137.0


# ══════════════════════════════════════════════════════════════════════
#  Utilitaires GPS
# ══════════════════════════════════════════════════════════════════════

def nmea_to_decimal(coord: str, direction: str) -> float:
    dot = coord.index('.')
    deg = int(coord[:dot - 2])
    minutes = float(coord[dot - 2:])
    v = deg + minutes / 60.0
    return -v if direction in ('S', 'W') else v


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def parse_time_s(time_str: str):
    try:
        t = time_str.replace(' UTC', '')
        h, m, s = t.split(':')
        return int(h)*3600 + int(m)*60 + float(s)
    except Exception:
        return None


def _smooth(data: list, window: int = 5) -> list:
    hw = window // 2
    out = []
    for i in range(len(data)):
        vals = [data[j] for j in range(max(0, i-hw), min(len(data), i+hw+1))
                if data[j] is not None]
        out.append(sum(vals)/len(vals) if vals else None)
    return out


def parse_gpgga(line: str):
    parts = line.strip().split(',')
    if len(parts) < 10:
        return None
    try:
        raw_t  = parts[1]
        fix    = int(parts[6]) if parts[6] else 0
        sats   = int(parts[7]) if parts[7] else 0
        hdop   = float(parts[8]) if parts[8] else None
        alt    = float(parts[9]) if parts[9] else None
    except (ValueError, IndexError):
        return None
    if fix == 0 or not parts[2] or not parts[4]:
        return None
    try:
        lat = nmea_to_decimal(parts[2], parts[3])
        lon = nmea_to_decimal(parts[4], parts[5])
    except (ValueError, IndexError):
        return None
    fmt = (f"{raw_t[0:2]}:{raw_t[2:4]}:{raw_t[4:]} UTC"
           if len(raw_t) >= 6 else raw_t)
    return {'time': fmt, 'lat': lat, 'lon': lon,
            'alt': alt, 'sats': sats, 'hdop': hdop}


def load_points(filepath: str) -> list:
    pts = []
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            if line.startswith('$GPGGA'):
                pt = parse_gpgga(line)
                if pt:
                    pts.append(pt)
    return pts


def to_webmerc(lat: float, lon: float):
    x = math.radians(lon) * WEB_MERC_R
    y = math.log(math.tan(math.radians(lat)/2 + math.pi/4)) * WEB_MERC_R
    return x, y


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
#  Modèle de données
# ══════════════════════════════════════════════════════════════════════

class GPSData:
    def __init__(self, points: list, filepath: str):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.points   = points
        n = len(points)

        # Distances cumulées (m)
        self.distances = [0.0]
        for i in range(1, n):
            self.distances.append(self.distances[-1] + haversine_m(
                points[i-1]['lat'], points[i-1]['lon'],
                points[i]['lat'],   points[i]['lon']))
        self.total_dist = self.distances[-1]

        # Altitudes
        self.alts = [p['alt'] for p in points]
        valid_a = [a for a in self.alts if a is not None]
        self.alt_min = min(valid_a) if valid_a else None
        self.alt_max = max(valid_a) if valid_a else None
        self.alt_avg = sum(valid_a)/len(valid_a) if valid_a else None

        # Vitesses (km/h), lissées
        raw_spd = [None]
        for i in range(1, n):
            t1 = parse_time_s(points[i-1]['time'])
            t2 = parse_time_s(points[i]['time'])
            dd = self.distances[i] - self.distances[i-1]
            if t1 is not None and t2 is not None:
                dt = t2 - t1
                if dt < 0:
                    dt += 86400
                raw_spd.append(dd / dt * 3.6 if dt > 0 else None)
            else:
                raw_spd.append(None)
        self.speeds = _smooth(raw_spd, window=5)
        valid_s = [s for s in self.speeds if s is not None]
        self.spd_max = max(valid_s) if valid_s else 0.0
        self.spd_avg = sum(valid_s)/len(valid_s) if valid_s else 0.0

        # Durée
        t0 = parse_time_s(points[0]['time'])
        tN = parse_time_s(points[-1]['time'])
        self.duration_s = None
        if t0 is not None and tN is not None:
            d = tN - t0
            self.duration_s = d + 86400 if d < 0 else d

        # Coordonnées Web Mercator (numpy)
        wm = [to_webmerc(p['lat'], p['lon']) for p in points]
        self.xs = np.array([w[0] for w in wm])
        self.ys = np.array([w[1] for w in wm])
        self.dist_arr = np.array(self.distances)

    @property
    def count(self) -> int:
        return len(self.points)


# ══════════════════════════════════════════════════════════════════════
#  Canvas Carte  (matplotlib + contextily OSM)
# ══════════════════════════════════════════════════════════════════════

class MapCanvas(FigureCanvas):
    def __init__(self):
        self.fig = Figure(facecolor='#2b2b2b')
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_axis_off()
        self._cursor_dot  = None
        self._gps: GPSData | None = None
        self._default_lim = None   # (xlim, ylim) pour reset
        self._tile_source   = cx.providers.OpenStreetMap.Mapnik
        self._tile_headers  = {}   # headers HTTP pour la source active

        # ── Cache LRU en mémoire ─────────────────────────────────────
        self._tile_cache  = _TileCache(maxsize=20)
        self._tile_worker: _TileWorker | None = None
        self._pending_key = None   # clé de la dernière requête en cours

        # ── Simplification de trace ──────────────────────────────────
        self._track_line  = None   # artist matplotlib de la trace

        # ── Indicateur de chargement ─────────────────────────────────
        self._loading_text = None  # text artist, None si axes vidés

        # ── État pan ────────────────────────────────────────────────
        self._pan_xy   = None   # position pixel au début du drag
        self._pan_lims = None   # (xlim, ylim) au début du drag

        # ── Timer rechargement tuiles (débounce 450 ms) ─────────────
        self._tile_timer = QTimer(singleShot=True, interval=450)
        self._tile_timer.timeout.connect(self._reload_tiles)

        # ── Événements souris ────────────────────────────────────────
        self.mpl_connect('scroll_event',         self._on_scroll)
        self.mpl_connect('button_press_event',   self._on_press)
        self.mpl_connect('motion_notify_event',  self._on_motion)
        self.mpl_connect('button_release_event', self._on_release)

        self.setCursor(Qt.OpenHandCursor)
        self._welcome()

    def _welcome(self):
        self.ax.set_facecolor('#2b2b2b')
        self.ax.text(0.5, 0.5,
                     'Ouvrir un fichier GPS\n(Fichier → Ouvrir  ou  Ctrl+O)',
                     transform=self.ax.transAxes, ha='center', va='center',
                     color='#888', fontsize=13, fontfamily='monospace')
        self.draw()

    # ── Chargement initial ───────────────────────────────────────────

    def load(self, gps: GPSData):
        self._gps = gps
        self._loading_text = None   # les ax.cla() invalident le text artist
        self._track_line   = None
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

        # Trace immédiatement visible ; tuiles chargées en arrière-plan
        self._draw_track()
        self._request_tiles()

        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.draw()

    def _draw_track(self):
        gps = self._gps
        xs, ys = self._simplified_track()
        self._track_line, = self.ax.plot(
            xs, ys, color=C_TRACK, linewidth=2.5, zorder=5,
            solid_capstyle='round', solid_joinstyle='round')
        self.ax.plot(gps.xs[0],  gps.ys[0],  'o',
                     color=C_START, markersize=13, zorder=7,
                     markeredgecolor='white', markeredgewidth=2, label='Départ')
        self.ax.plot(gps.xs[-1], gps.ys[-1], 's',
                     color=C_END, markersize=12, zorder=7,
                     markeredgecolor='white', markeredgewidth=2, label='Arrivée')
        self.ax.legend(loc='upper left', fontsize=9,
                       framealpha=0.85, fancybox=True)
        self._cursor_dot, = self.ax.plot([], [], 'o',
            color=C_CURSOR, markersize=12, zorder=10,
            markeredgecolor='white', markeredgewidth=1.5, visible=False)

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

    def _simplified_track(self):
        """Retourne (xs, ys) avec Douglas-Peucker si la trace > 500 pts."""
        gps = self._gps
        if gps is None or gps.count < 500:
            return gps.xs, gps.ys
        mask = _douglas_peucker_mask(gps.xs, gps.ys, self._dp_epsilon())
        return gps.xs[mask], gps.ys[mask]

    def _redraw_track_line(self):
        """Remplace le polyline de la trace avec la simplification courante."""
        if self._track_line is not None:
            self._track_line.remove()
            self._track_line = None
        if self._gps is None:
            return
        xs, ys = self._simplified_track()
        self._track_line, = self.ax.plot(
            xs, ys, color=C_TRACK, linewidth=2.5, zorder=5,
            solid_capstyle='round', solid_joinstyle='round')

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
            return

        self._pending_key  = key
        self._show_loading()
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

    def _on_tiles_failed(self, msg: str):
        self._hide_loading()
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

    # ── Rechargement tuiles après zoom/pan ──────────────────────────

    def _reload_tiles(self):
        if self._default_lim is None:
            return
        # Met à jour la simplification Douglas-Peucker si la trace est grande
        if self._gps is not None and self._gps.count >= 500:
            self._redraw_track_line()
        self._request_tiles()

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
        self.draw_idle()
        self._tile_timer.start()   # recharge les tuiles 450 ms après le dernier scroll

    # ── Pan (clic gauche + glisser) ──────────────────────────────────

    def _on_press(self, event):
        if event.button == 1 and event.inaxes == self.ax and self._default_lim is not None:
            self._pan_xy   = (event.x, event.y)
            self._pan_lims = (self.ax.get_xlim(), self.ax.get_ylim())
            self.setCursor(Qt.ClosedHandCursor)

    def _on_motion(self, event):
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
        if event.button == 1 and self._pan_xy is not None:
            self._pan_xy = None
            self.setCursor(Qt.OpenHandCursor)
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

        self._gps          = None
        self._cursor_dot   = None
        self._loading_text = None
        self._track_line   = None
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

        self._request_tiles()
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self.draw()

    # ── Curseur synchronisé avec les graphiques ──────────────────────

    def update_cursor(self, index):
        if self._cursor_dot is None or self._gps is None:
            return
        if index is not None and 0 <= index < self._gps.count:
            self._cursor_dot.set_data([self._gps.xs[index]],
                                      [self._gps.ys[index]])
            self._cursor_dot.set_visible(True)
        else:
            self._cursor_dot.set_visible(False)
        self.draw_idle()


# ══════════════════════════════════════════════════════════════════════
#  Canvas Graphique  (altitude ou vitesse)
# ══════════════════════════════════════════════════════════════════════

class ChartCanvas(FigureCanvas):
    def __init__(self, title: str, color: str, on_hover):
        self.fig = Figure(facecolor='#f7f8fa')
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax     = self.fig.add_subplot(111)
        self._title = title
        self._color = color
        self._on_hover = on_hover
        self._vline    = None
        self._dist_arr = None
        self._draw_empty()
        self.mpl_connect('motion_notify_event', self._mouse_move)
        self.mpl_connect('axes_leave_event',    lambda _: on_hover(None))
        self.mpl_connect('figure_leave_event',  lambda _: on_hover(None))

    def _style_ax(self):
        self.ax.set_facecolor('#ffffff')
        self.ax.tick_params(colors='#888', labelsize=9, which='both')
        for sp in self.ax.spines.values():
            sp.set_edgecolor('#e0e0e0')
        self.ax.grid(True, color='#eeeeee', linewidth=0.8, zorder=0)
        self.ax.set_title(self._title, fontsize=10.5, color='#444',
                          fontweight='semibold', pad=5)
        self.ax.set_xlabel('Distance (m)', fontsize=9, color='#888',
                           labelpad=3)

    def _draw_empty(self):
        self.ax.cla()
        self._style_ax()
        self.ax.text(0.5, 0.5, '—', transform=self.ax.transAxes,
                     ha='center', va='center', color='#ccc', fontsize=20)
        self.fig.tight_layout(pad=0.8)
        self.draw()

    def load(self, distances: list, data: list, ylabel: str):
        self._dist_arr = np.array(distances)
        self.ax.cla()
        self._style_ax()
        self.ax.set_ylabel(ylabel, fontsize=9, color='#888', labelpad=3)

        valid = [(d, v) for d, v in zip(distances, data) if v is not None]
        if valid:
            ds, vs = zip(*valid)
            ds, vs = np.array(ds), np.array(vs)
            vmin, vmax = vs.min(), vs.max()
            pad = max(0.5, (vmax - vmin) * 0.18)
            self.ax.fill_between(ds, vs, alpha=0.16, color=self._color, zorder=1)
            self.ax.plot(ds, vs, color=self._color, linewidth=1.8,
                         zorder=2, solid_capstyle='round')
            self.ax.set_ylim(vmin - pad, vmax + pad)
            self.ax.set_xlim(ds[0], ds[-1])

        self._vline = self.ax.axvline(
            x=0, color=C_CURSOR, linewidth=1.6,
            linestyle='--', visible=False, zorder=5)

        self.fig.tight_layout(pad=0.8)
        self.draw()

    def update_cursor(self, index):
        if self._vline is None or self._dist_arr is None:
            return
        if index is not None and 0 <= index < len(self._dist_arr):
            self._vline.set_xdata([self._dist_arr[index]])
            self._vline.set_visible(True)
        else:
            self._vline.set_visible(False)
        self.draw_idle()

    def _mouse_move(self, event):
        if event.inaxes != self.ax or self._dist_arr is None:
            return
        idx = int(np.argmin(np.abs(self._dist_arr - event.xdata)))
        self._on_hover(idx)


# ══════════════════════════════════════════════════════════════════════
#  Panneau de statistiques
# ══════════════════════════════════════════════════════════════════════

class StatsPanel(QFrame):
    _FIELDS = [
        ('Fichier',      None),
        ('Points GPS',   None),
        ('Distance',     None),
        ('Durée',        None),
        ('Altitude min', None),
        ('Altitude max', None),
        ('Alt. moyenne', None),
        ('Vitesse max',  None),
        ('Vitesse moy.', None),
    ]

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(210)
        self.setStyleSheet(
            'StatsPanel { background:#fafafa; border-left:1px solid #ddd; }')

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 10)
        root.setSpacing(0)

        # ── Titre bloc statistiques ──
        lbl_title = QLabel('STATISTIQUES')
        lbl_title.setFont(QFont('Arial', 8, QFont.Bold))
        lbl_title.setStyleSheet('color:#777; letter-spacing:1.2px;')
        root.addWidget(lbl_title)
        root.addSpacing(6)

        self._vals: dict[str, QLabel] = {}
        for key, _ in self._FIELDS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            lk = QLabel(key)
            lk.setFont(QFont('Arial', 9))
            lk.setStyleSheet('color:#999;')
            lk.setFixedWidth(90)
            lk.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            lv = QLabel('—')
            lv.setFont(QFont('Arial', 9, QFont.Bold))
            lv.setStyleSheet('color:#222;')
            lv.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lv.setWordWrap(True)

            row.addWidget(lk)
            row.addSpacing(6)
            row.addWidget(lv, 1)
            root.addLayout(row)
            self._vals[key] = lv

        # ── Séparateur ──
        root.addSpacing(10)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('background:#e0e0e0; max-height:1px;')
        root.addWidget(sep)
        root.addSpacing(8)

        # ── Titre bloc curseur ──
        lbl_cur = QLabel('CURSEUR')
        lbl_cur.setFont(QFont('Arial', 8, QFont.Bold))
        lbl_cur.setStyleSheet('color:#777; letter-spacing:1.2px;')
        root.addWidget(lbl_cur)
        root.addSpacing(6)

        self._hover = QLabel('—\n\n\n\n\n')
        self._hover.setFont(QFont('Courier', 9))
        self._hover.setStyleSheet('color:#333; line-height:160%;')
        self._hover.setWordWrap(True)
        self._hover.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self._hover)

        root.addStretch()

        # ── Crédits ──
        credits = QLabel('© OpenStreetMap contributors')
        credits.setFont(QFont('Arial', 7))
        credits.setStyleSheet('color:#bbb;')
        credits.setAlignment(Qt.AlignCenter)
        root.addWidget(credits)

    def refresh(self, gps: GPSData):
        dur = '—'
        if gps.duration_s is not None:
            h  = int(gps.duration_s // 3600)
            mn = int((gps.duration_s % 3600) // 60)
            s  = int(gps.duration_s % 60)
            dur = (f"{h}h {mn:02d}min {s:02d}s" if h
                   else f"{mn}min {s:02d}s")

        self._set('Fichier',      gps.filename)
        self._set('Points GPS',   f"{gps.count:,}")
        self._set('Distance',     f"{gps.total_dist:.1f} m")
        self._set('Durée',        dur)
        self._set('Altitude min', f"{gps.alt_min:.1f} m"  if gps.alt_min is not None else '—')
        self._set('Altitude max', f"{gps.alt_max:.1f} m"  if gps.alt_max is not None else '—')
        self._set('Alt. moyenne', f"{gps.alt_avg:.1f} m"  if gps.alt_avg is not None else '—')
        self._set('Vitesse max',  f"{gps.spd_max:.1f} km/h")
        self._set('Vitesse moy.', f"{gps.spd_avg:.1f} km/h")
        self._hover.setText('—')

    def update_cursor(self, gps: GPSData, index: int | None):
        if index is None or index >= gps.count:
            self._hover.setText('—')
            return
        p   = gps.points[index]
        spd = gps.speeds[index]
        alt = p['alt']
        lines = [
            f"Heure : {p['time']}",
            f"Lat   : {p['lat']:.5f}°",
            f"Lon   : {p['lon']:.5f}°",
            f"Alt   : {f'{alt:.1f} m' if alt is not None else '—'}",
            f"Vit   : {f'{spd:.1f} km/h' if spd is not None else '—'}",
            f"Dist  : {gps.distances[index]:.0f} m",
            f"Sats  : {p['sats']}",
        ]
        self._hover.setText('\n'.join(lines))

    def _set(self, key: str, val: str):
        if key in self._vals:
            self._vals[key].setText(val)


# ══════════════════════════════════════════════════════════════════════
#  Dialogue de navigation par coordonnées
# ══════════════════════════════════════════════════════════════════════

class CoordDialog(QDialog):
    """Fenêtre de saisie de coordonnées GPS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Aller aux coordonnées')
        self.setFixedSize(380, 260)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Champ de collage rapide ──────────────────────────────────
        lbl_paste = QLabel('Coller des coordonnées (lat, lon) :')
        lbl_paste.setStyleSheet('font-weight:bold; color:#444;')
        layout.addWidget(lbl_paste)

        self._paste = QLineEdit()
        self._paste.setPlaceholderText('Ex : 48.8566, 2.3522')
        self._paste.textChanged.connect(self._parse_paste)
        layout.addWidget(self._paste)

        # ── Grille lat / lon / zoom ──────────────────────────────────
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel('Latitude :'), 0, 0)
        self._lat = QDoubleSpinBox()
        self._lat.setRange(-90.0, 90.0)
        self._lat.setDecimals(6)
        self._lat.setSingleStep(0.001)
        self._lat.setValue(48.8566)
        self._lat.setSuffix(' °')
        grid.addWidget(self._lat, 0, 1)

        grid.addWidget(QLabel('Longitude :'), 1, 0)
        self._lon = QDoubleSpinBox()
        self._lon.setRange(-180.0, 180.0)
        self._lon.setDecimals(6)
        self._lon.setSingleStep(0.001)
        self._lon.setValue(2.3522)
        self._lon.setSuffix(' °')
        grid.addWidget(self._lon, 1, 1)

        grid.addWidget(QLabel('Zoom :'), 2, 0)
        self._zoom = QSpinBox()
        self._zoom.setRange(1, 19)
        self._zoom.setValue(16)
        self._zoom.setToolTip('1 = monde entier · 10 = ville · 16 = rue · 19 = très détaillé')
        grid.addWidget(self._zoom, 2, 1)

        layout.addLayout(grid)

        # ── Exemples ─────────────────────────────────────────────────
        ex = QLabel('Exemples : Paris 48.8566, 2.3522 · Strasbourg 48.5734, 7.7521 · Lyon 45.7640, 4.8357')
        ex.setStyleSheet('color:#999; font-size:10px;')
        ex.setWordWrap(True)
        layout.addWidget(ex)

        # ── Boutons OK / Annuler ─────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText('Aller')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _parse_paste(self, text: str):
        """Extrait lat, lon depuis une chaîne 'lat, lon' collée."""
        parts = text.strip().replace(';', ',').split(',')
        if len(parts) >= 2:
            try:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    self._lat.setValue(lat)
                    self._lon.setValue(lon)
            except ValueError:
                pass

    def coords(self):
        """Retourne (lat, lon, zoom)."""
        return self._lat.value(), self._lon.value(), self._zoom.value()


# ══════════════════════════════════════════════════════════════════════
#  Fenêtre principale
# ══════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('GPS Viewer')
        self.resize(1380, 840)
        self._gps: GPSData | None = None
        self._build_ui()
        self._build_menus()
        self.setAcceptDrops(True)

    # ── Interface ────────────────────────────────────────────────────

    def _build_ui(self):
        # Toolbar
        tb = QToolBar(self)
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setStyleSheet('QToolBar { spacing: 4px; padding: 3px 6px; '
                         'background: #f0f0f0; border-bottom: 1px solid #ccc; }')
        self.addToolBar(tb)

        act_open = QAction('📂  Ouvrir', self)
        act_open.setShortcut('Ctrl+O')
        act_open.setToolTip('Ouvrir un fichier GPS NMEA (Ctrl+O)')
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

        # Status bar
        self._sb = QStatusBar()
        self._sb.setStyleSheet('font-size:11px; color:#555;')
        self.setStatusBar(self._sb)
        size_mb = _cache_size_mb()
        cache_msg = f'{size_mb:.1f} Mo en cache' if size_mb >= 0.01 else 'cache vide'
        self._sb.showMessage(f'Prêt — Ouvrir un fichier GPS pour commencer  •  {cache_msg}')

    def _build_menus(self):
        mb = self.menuBar()

        fm = mb.addMenu('Fichier')
        a = QAction('Ouvrir…', self)
        a.setShortcut('Ctrl+O')
        a.triggered.connect(self._open_dialog)
        fm.addAction(a)

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

        self._gps = GPSData(points, filepath)
        self._map.load(self._gps)
        self._chart_alt.load(self._gps.distances, self._gps.alts,  'Altitude (m)')
        self._chart_spd.load(self._gps.distances, self._gps.speeds,'Vitesse (km/h)')
        self._stats.refresh(self._gps)

        self.setWindowTitle(f'GPS Viewer — {self._gps.filename}')
        self._lbl_tb.setText(
            f'<b>{self._gps.filename}</b>'
            f' &nbsp;|&nbsp; {self._gps.count:,} points'
            f' &nbsp;|&nbsp; {self._gps.total_dist:.0f} m'
            + (f' &nbsp;|&nbsp; Alt {self._gps.alt_min:.0f}–'
               f'{self._gps.alt_max:.0f} m'
               if self._gps.alt_min is not None else '')
            + f' &nbsp;|&nbsp; Vmax {self._gps.spd_max:.1f} km/h'
        )
        self._sb.showMessage(
            f'{self._gps.filename} — {self._gps.count:,} positions valides  •  '
            f'Distance : {self._gps.total_dist:.1f} m  •  '
            f'Vmax : {self._gps.spd_max:.1f} km/h')

    # ── Curseur synchronisé ──────────────────────────────────────────

    def _on_hover(self, index):
        self._map.update_cursor(index)
        self._chart_alt.update_cursor(index)
        self._chart_spd.update_cursor(index)
        if self._gps:
            self._stats.update_cursor(self._gps, index)

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

    win = MainWindow()
    win.show()

    # Auto-chargement
    if len(sys.argv) > 1:
        win._load(sys.argv[1])
    else:
        candidates = sorted(glob.glob('GPS*.txt') + glob.glob('gps*.txt'))
        if candidates:
            win._load(candidates[-1])

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
