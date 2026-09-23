"""
map_tiles.py — Infrastructure de chargement des tuiles cartographiques :
             cache disque persistant, cache LRU de tuiles en mémoire,
             TileLoader (téléchargement parallèle tuile par tuile), thread
             des courbes de niveau SRTM et simplification de trace
             Douglas-Peucker. Extrait de map_canvas.py (qui l'utilise et le
             réexporte) pour garder ce dernier plus lisible.
"""

import hashlib
import io
import math
import socket
import sys
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import contextily as cx
import requests
import xyzservices
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import (ConnectTimeoutError, NameResolutionError,
                                NewConnectionError)
from PIL import Image as PilImage

from PyQt5.QtCore import QCoreApplication, QObject, QThread, pyqtSignal

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
#  Géométrie des tuiles XYZ (Web Mercator / EPSG:3857)
# ══════════════════════════════════════════════════════════════════════

TILE_PX       = 256
_MERC_HALF    = math.pi * 6_378_137.0      # demi-circonférence équatoriale (m)
_MERC_EXTENT  = 2 * _MERC_HALF


def tile_size_m(z: int) -> float:
    """Côté d'une tuile de niveau z, en mètres Web Mercator."""
    return _MERC_EXTENT / (1 << z)


def tile_range(xl, yl, z: int):
    """Tuiles couvrant la vue (xl, yl) : (x0, x1, y0, y1) inclus, bornés au monde."""
    ts, n = tile_size_m(z), 1 << z
    x0 = int(math.floor((xl[0] + _MERC_HALF) / ts))
    x1 = int(math.floor((xl[1] + _MERC_HALF) / ts))
    y0 = int(math.floor((_MERC_HALF - yl[1]) / ts))   # rangée 0 = nord
    y1 = int(math.floor((_MERC_HALF - yl[0]) / ts))
    clamp = lambda v: max(0, min(n - 1, v))           # noqa: E731
    return clamp(x0), clamp(x1), clamp(y0), clamp(y1)


def tiles_extent(x0: int, x1: int, y0: int, y1: int, z: int):
    """Emprise (left, right, bottom, top) en mètres d'un bloc de tuiles."""
    ts = tile_size_m(z)
    return (x0 * ts - _MERC_HALF, (x1 + 1) * ts - _MERC_HALF,
            _MERC_HALF - (y1 + 1) * ts, _MERC_HALF - y0 * ts)


def provider_for(source):
    """Normalise une source (TileProvider xyzservices ou URL '{z}/{x}/{y}')."""
    if isinstance(source, str):
        return xyzservices.TileProvider(name='url', url=source, attribution='')
    return source


# ══════════════════════════════════════════════════════════════════════
#  Cache LRU en mémoire (tuiles décodées)
# ══════════════════════════════════════════════════════════════════════

class _TileCache:
    """LRU cache de tuiles décodées : rend les aller-retours instantanés.
    Thread-safe (alimenté par les threads de TileLoader, lu par le GUI)."""

    def __init__(self, maxsize: int = 20):
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key, value):
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def __len__(self):
        return len(self._cache)


# ══════════════════════════════════════════════════════════════════════
#  Connexions HTTP avec repli IPv6 → IPv4 (« Happy Eyeballs » simplifié)
# ══════════════════════════════════════════════════════════════════════
# urllib3 essaie les adresses d'un serveur l'une après l'autre, chacune avec
# le délai de connexion complet. Sur un réseau où l'IPv6 est annoncé mais ne
# passe pas, un serveur à plusieurs adresses IPv6 (CDN : Esri/CloudFront…)
# coûte alors 5 s × N avant d'arriver à l'IPv4 — ~40 s constatés. Ici on
# alterne les familles (RFC 8305), on borne chaque essai non final à
# _FALLBACK_TIMEOUT et on mémorise par serveur la famille qui a répondu.

_FALLBACK_TIMEOUT = 1.0
_preferred_family: dict = {}          # hôte → socket.AF_INET / AF_INET6
_preferred_lock = threading.Lock()


def _ordered_addrinfo(host: str, port: int) -> list:
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    with _preferred_lock:
        pref = _preferred_family.get(host)
    if pref is not None:
        return sorted(infos, key=lambda ai: ai[0] != pref)
    v6 = [ai for ai in infos if ai[0] == socket.AF_INET6]
    v4 = [ai for ai in infos if ai[0] != socket.AF_INET6]
    ordered = []
    for k in range(max(len(v6), len(v4))):
        ordered += v6[k:k + 1] + v4[k:k + 1]
    return ordered


def _connect_with_fallback(host: str, port: int, timeout,
                           source_address=None, socket_options=None):
    """Équivalent de urllib3.util.connection.create_connection avec repli
    rapide d'une famille d'adresses à l'autre."""
    if host.startswith('['):
        host = host.strip('[]')
    infos = _ordered_addrinfo(host, port)
    if not infos:
        raise OSError('getaddrinfo returns an empty list')
    full = timeout if isinstance(timeout, (int, float)) else None
    err = None
    for n, (af, socktype, proto, _, sa) in enumerate(infos):
        last = n == len(infos) - 1
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            for opt in socket_options or ():
                sock.setsockopt(*opt)
            if last:
                sock.settimeout(full)
            else:
                sock.settimeout(_FALLBACK_TIMEOUT if full is None
                                else min(full, _FALLBACK_TIMEOUT))
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            sock.settimeout(full)
            with _preferred_lock:
                _preferred_family[host] = af
            return sock
        except OSError as exc:
            err = exc
            if sock is not None:
                sock.close()
    raise err


class _FallbackConnMixin:
    def _new_conn(self) -> socket.socket:
        # Reprend HTTPConnection._new_conn (urllib3 2.x) avec notre connexion
        try:
            sock = _connect_with_fallback(
                self._dns_host, self.port, self.timeout,
                source_address=self.source_address,
                socket_options=self.socket_options)
        except socket.gaierror as e:
            raise NameResolutionError(self.host, self, e) from e
        except socket.timeout as e:
            raise ConnectTimeoutError(
                self, f'Connection to {self.host} timed out. '
                      f'(connect timeout={self.timeout})') from e
        except OSError as e:
            raise NewConnectionError(
                self, f'Failed to establish a new connection: {e}') from e
        sys.audit('http.client.connect', self, self.host, self.port)
        return sock


class _FallbackHTTPConnection(_FallbackConnMixin, HTTPConnection):
    pass


class _FallbackHTTPSConnection(_FallbackConnMixin, HTTPSConnection):
    pass


class _FallbackHTTPPool(HTTPConnectionPool):
    ConnectionCls = _FallbackHTTPConnection


class _FallbackHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _FallbackHTTPSConnection


class _FallbackAdapter(HTTPAdapter):
    """Adaptateur requests utilisant les connexions avec repli IPv6 → IPv4."""

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            'http': _FallbackHTTPPool, 'https': _FallbackHTTPSPool}


# ══════════════════════════════════════════════════════════════════════
#  Chargeur de tuiles : disque → réseau, en parallèle, tuile par tuile
# ══════════════════════════════════════════════════════════════════════

class TileLoader(QObject):
    """Charge des tuiles XYZ individuelles en arrière-plan.

    Chaque tuile passe par : cache mémoire (get_cached, synchrone) → cache
    disque (_TILE_CACHE_DIR/xyz/…, pool de lecture dédié) → réseau. Les
    téléchargements se font en parallèle, dans un pool séparé limité selon
    la source, sur des sessions HTTP keep-alive (une par thread), ce qui
    évite une poignée de main TLS par tuile. Les résultats arrivent dans le thread
    GUI via les signaux (connexion en file d'attente Qt).
    """
    tile_ready  = pyqtSignal(str, int, int, int, object)  # src_key, z, x, y, img RGB
    tile_failed = pyqtSignal(str, int, int, int, str)     # src_key, z, x, y, message

    # Politique d'usage des tuiles OSM : 2 connexions simultanées au plus
    # (https://operations.osmfoundation.org/policies/tiles/).
    _OSM_WORKERS   = 2
    _OTHER_WORKERS = 6
    _DISK_WORKERS  = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem       = _TileCache(maxsize=400)   # ~80 Mo de tuiles RGB 256²
        self._local     = threading.local()
        self._inflight: dict = {}                   # (src_key, z, x, y) → Future
        self._inflight_lock = threading.Lock()
        self._closing   = False
        self._provider  = None
        self._src_key   = ''
        self._headers: dict = {}
        self._executor  = None                      # réseau (recréé par source)
        self._disk_pool = ThreadPoolExecutor(max_workers=self._DISK_WORKERS,
                                             thread_name_prefix='tiles-disk')
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    # ── Source ───────────────────────────────────────────────────────

    def set_source(self, source, headers: dict | None = None) -> str:
        """Change la source de tuiles ; retourne sa clé (préfixe de cache)."""
        provider = provider_for(source)
        url = provider.build_url(x='{x}', y='{y}', z='{z}')
        self._provider = provider
        self._headers  = dict(headers or {})
        self._src_key  = hashlib.sha1(url.encode()).hexdigest()[:12]
        workers = (self._OSM_WORKERS if 'openstreetmap.org' in url
                   else self._OTHER_WORKERS)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        with self._inflight_lock:
            self._inflight.clear()
        self._executor = ThreadPoolExecutor(max_workers=workers,
                                            thread_name_prefix='tiles')
        return self._src_key

    @property
    def src_key(self) -> str:
        return self._src_key

    @property
    def max_zoom(self) -> int:
        return int(self._provider.get('max_zoom', 19)) if self._provider else 19

    # ── Requêtes ─────────────────────────────────────────────────────

    def get_cached(self, z: int, x: int, y: int):
        """Tuile décodée si présente en mémoire, sinon None (sans I/O)."""
        return self._mem.get((self._src_key, z, x, y))

    def request(self, tiles: list) -> None:
        """Demande les tuiles [(z, x, y), …] dans l'ordre de priorité donné.

        Les demandes précédentes pas encore démarrées et absentes de la
        nouvelle liste sont annulées (zoom/pan rapide : on ne télécharge
        pas des vues déjà quittées)."""
        if self._closing or self._executor is None:
            return
        wanted = {(self._src_key, z, x, y) for z, x, y in tiles}
        with self._inflight_lock:
            stale = [(k, f) for k, f in self._inflight.items() if k not in wanted]
        for key, fut in stale:
            fut.cancel()        # sans effet si déjà démarrée : elle se termine
        for z, x, y in tiles:
            key = (self._src_key, z, x, y)
            with self._inflight_lock:
                if key in self._inflight:
                    continue
            url = self._provider.build_url(x=x, y=y, z=z)
            fut = self._disk_pool.submit(self._load_disk, key, url,
                                         dict(self._headers), self._executor)
            with self._inflight_lock:
                self._inflight[key] = fut
            fut.add_done_callback(lambda _f, k=key: self._forget(k, _f))

    def _forget(self, key, fut) -> None:
        with self._inflight_lock:
            if self._inflight.get(key) is fut:
                del self._inflight[key]

    def shutdown(self) -> None:
        """Annule les téléchargements en attente (fermeture de l'application)."""
        self._closing = True
        self._disk_pool.shutdown(wait=False, cancel_futures=True)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # ── Thread de travail ────────────────────────────────────────────

    def _session(self) -> requests.Session:
        sess = getattr(self._local, 'session', None)
        if sess is None:
            sess = self._local.session = requests.Session()
            adapter = _FallbackAdapter()
            sess.mount('http://', adapter)
            sess.mount('https://', adapter)
        return sess

    @staticmethod
    def _disk_path(key) -> Path:
        src_key, z, x, y = key
        return _TILE_CACHE_DIR / 'xyz' / src_key / str(z) / str(x) / f'{y}.tile'

    def _load_disk(self, key, url: str, headers: dict, net_pool) -> None:
        """Pool disque : lit la tuile en cache, sinon la confie au pool réseau."""
        if self._closing:
            return
        path = self._disk_path(key)
        if path.exists():
            try:
                self._deliver(key, _decode_tile(path.read_bytes()))
                return
            except Exception:
                pass                                # fichier corrompu : re-téléchargement
        try:
            fut = net_pool.submit(self._download, key, url, headers)
        except RuntimeError:
            return                                  # source changée entre-temps
        with self._inflight_lock:
            if key in self._inflight:
                self._inflight[key] = fut           # suivi (et annulation) côté réseau
        fut.add_done_callback(lambda _f, k=key: self._forget(k, _f))

    def _download(self, key, url: str, headers: dict) -> None:
        """Pool réseau : télécharge, valide, écrit sur disque puis livre."""
        if self._closing:
            return
        try:
            resp = self._session().get(url, headers=headers, timeout=(5, 10))
            resp.raise_for_status()
            img  = _decode_tile(resp.content)       # valide l'image avant de la cacher
            path = self._disk_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f'.tmp{threading.get_ident()}')
            tmp.write_bytes(resp.content)
            tmp.replace(path)
            self._deliver(key, img)
        except Exception as exc:
            if not self._closing:
                self.tile_failed.emit(*key, str(exc))

    def _deliver(self, key, img) -> None:
        self._mem.put(key, img)
        if not self._closing:
            self.tile_ready.emit(*key, img)


def _decode_tile(data: bytes) -> np.ndarray:
    """Décode une tuile PNG/JPEG en tableau RGB uint8 (TILE_PX × TILE_PX)."""
    img = PilImage.open(io.BytesIO(data)).convert('RGB')
    if img.size != (TILE_PX, TILE_PX):
        img = img.resize((TILE_PX, TILE_PX), PilImage.BILINEAR)
    return np.asarray(img)


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
