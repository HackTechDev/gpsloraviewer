"""
map_tiles.py — Infrastructure de chargement des tuiles cartographiques :
             cache disque persistant, cache LRU en mémoire, threads réseau
             (tuiles OSM, courbes de niveau SRTM) et simplification de trace
             Douglas-Peucker. Extrait de map_canvas.py (qui l'utilise et le
             réexporte) pour garder ce dernier plus lisible.
"""

import math
from collections import OrderedDict
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure
import contextily as cx

from PyQt5.QtCore import QThread, pyqtSignal

# ── Threads réseau annulés mais encore actifs ──────────────────────────
# cancel() est coopératif : il ne peut pas interrompre un appel réseau déjà
# bloquant (contextily/requests). Si on abandonne la référence Python d'un
# QThread pendant qu'il tourne encore (remplacement par un nouveau worker,
# reset(), fermeture de fenêtre…), Qt détruit l'objet C++ sous-jacent et
# plante avec « QThread: Destroyed while thread is still running ». On garde
# donc une référence ici jusqu'à la fin réelle du thread (signal `finished`).
_retired_threads: list = []


def _retire_thread(thread) -> None:
    if thread is None or not thread.isRunning():
        return
    _retired_threads.append(thread)
    thread.finished.connect(
        lambda: thread in _retired_threads and _retired_threads.remove(thread))


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
                           headers=self._headers or None,
                           # (connect, read) par tuile — évite un blocage
                           # indéfini si le serveur ne répond pas ; le
                           # timeout HTTP ne couvre pas une résolution DNS
                           # bloquée, d'où le garde-fou _tile_watchdog côté UI.
                           timeout=(5, 10))
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
