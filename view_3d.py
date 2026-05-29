"""
view_3d.py — Fenêtre de visualisation 3D de la trace GPS
           (matplotlib Axes3D + tuiles OSM chargées en arrière-plan)
"""

import numpy as np
import matplotlib
import matplotlib.colors as mcolors
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d import Axes3D           # noqa: F401 — enregistrement side-effect
from mpl_toolkits.mplot3d.art3d import Line3DCollection

import contextily as cx

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QToolBar, QAction,
    QLabel, QComboBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, QSize, QThread, QTimer, pyqtSignal

from gps_nmea import GPSData
from map_canvas import _TRACK_PALETTE, _CMAP_ALT, _CMAP_SPD


# ── Worker : téléchargement des tuiles OSM hors thread principal ──────

class _TileFetcher(QThread):
    tile_ready = pyqtSignal(object, object, int)   # img, ext, draw_id

    def __init__(self, west: float, south: float,
                 east: float, north: float, draw_id: int):
        super().__init__()
        self._bounds  = (west, south, east, north)
        self._draw_id = draw_id
        self._cancel  = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            img, ext = cx.bounds2img(*self._bounds, zoom='auto',
                                      source=cx.providers.OpenStreetMap.Mapnik)
            if not self._cancel:
                self.tile_ready.emit(img, ext, self._draw_id)
        except Exception:
            if not self._cancel:
                self.tile_ready.emit(None, None, self._draw_id)


# ── Helpers ───────────────────────────────────────────────────────────

def _fill_none(values: list, dtype=float) -> np.ndarray:
    """Convertit une liste avec None en ndarray, NaN remplacé par la médiane."""
    arr = np.array([v if v is not None else np.nan for v in values], dtype=dtype)
    if np.all(np.isnan(arr)):
        return np.zeros(len(arr), dtype=dtype)
    median = float(np.nanmedian(arr))
    return np.where(np.isnan(arr), median, arr)


def _make_segments(xs, ys, zs) -> np.ndarray:
    """Retourne un tableau (N-1, 2, 3) de segments consécutifs."""
    pts = np.stack([xs, ys, zs], axis=1)
    return np.stack([pts[:-1], pts[1:]], axis=1)


# ══════════════════════════════════════════════════════════════════════
#  Fenêtre Vue 3D
# ══════════════════════════════════════════════════════════════════════

class View3DWindow(QDialog):
    def __init__(self, gps_list: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Vue 3D — GPS Viewer')
        self.resize(960, 680)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowMinimizeButtonHint
        )

        self._gps_list    = gps_list
        self._color_mode  = 'flat'   # 'flat' | 'altitude' | 'speed'
        self._show_map    = True
        self._draw_id     = 0
        self._tile_fetcher: '_TileFetcher | None' = None
        self._map_surface = None     # référence au plot_surface OSM
        # Mémorisés pour l'application différée des tuiles
        self._x_ref   = 0.0
        self._y_ref   = 0.0
        self._z_floor = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Barre d'outils ───────────────────────────────────────────
        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setStyleSheet(
            'QToolBar { background:#f0f0f0; border-bottom:1px solid #ccc;'
            ' spacing:4px; padding:3px 6px; }')

        lbl = QLabel('Coloration :')
        lbl.setStyleSheet('font-size:12px; color:#555; padding:0 4px;')
        tb.addWidget(lbl)

        self._combo = QComboBox()
        self._combo.addItems(['— Couleur unie', '🏔  Altitude', '⚡  Vitesse'])
        self._combo.setFixedWidth(170)
        self._combo.setToolTip('Mode de coloration de la trace')
        self._combo.currentIndexChanged.connect(self._on_color_mode)
        tb.addWidget(self._combo)

        tb.addSeparator()

        self._act_map = QAction('🗺  Fond OSM', self)
        self._act_map.setCheckable(True)
        self._act_map.setChecked(True)
        self._act_map.setToolTip('Afficher / masquer le fond de carte OpenStreetMap')
        self._act_map.triggered.connect(self._on_toggle_map)
        tb.addAction(self._act_map)

        tb.addSeparator()

        act_reset = QAction('⌂  Réinitialiser la vue', self)
        act_reset.setToolTip("Revenir à l'angle de vue par défaut")
        act_reset.triggered.connect(self._reset_view)
        tb.addAction(act_reset)

        root.addWidget(tb)

        # ── Canvas matplotlib ────────────────────────────────────────
        self._fig    = Figure(facecolor='#1a2535')
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._canvas)

        # Masquer la carte pendant les interactions souris (rotation/pan)
        # pour que chaque frame soit calculée sans les polygones OSM
        self._canvas.mpl_connect('button_press_event',   self._on_rot_start)
        self._canvas.mpl_connect('button_release_event', self._on_rot_end)
        # Empêcher la caméra de passer sous le plan horizontal
        self._canvas.mpl_connect('motion_notify_event',  self._on_mouse_move)

        # Différer le rendu pour que la fenêtre s'affiche avant de bloquer
        QTimer.singleShot(0, self._draw)

    # ── Cycle de vie ─────────────────────────────────────────────────

    def closeEvent(self, event):
        self._cancel_fetch()
        super().closeEvent(event)

    def _cancel_fetch(self):
        if self._tile_fetcher and self._tile_fetcher.isRunning():
            self._tile_fetcher.cancel()
            try:
                self._tile_fetcher.tile_ready.disconnect()
            except TypeError:
                pass

    def _on_rot_start(self, event):
        """Cache la surface OSM dès qu'une interaction souris débute."""
        if self._map_surface is not None:
            self._map_surface.set_visible(False)

    def _on_rot_end(self, event):
        """Réaffiche la surface OSM une fois l'interaction terminée."""
        if self._map_surface is not None:
            self._map_surface.set_visible(True)
            self._canvas.draw_idle()

    def _on_mouse_move(self, event):
        """Empêche la caméra de passer sous le plan horizontal (elev < 0)."""
        if not self._fig.axes:
            return
        ax = self._fig.axes[0]
        if hasattr(ax, 'elev') and ax.elev < 0:
            ax.elev = 0
            self._canvas.draw_idle()

    # ── Slots ────────────────────────────────────────────────────────

    def _on_color_mode(self, idx: int):
        self._color_mode = ('flat', 'altitude', 'speed')[idx]
        self._draw()

    def _on_toggle_map(self, checked: bool):
        self._show_map = checked
        self._draw()

    def refresh(self, gps_list: list):
        """Met à jour les données et redessine."""
        self._gps_list = gps_list
        self._draw()

    # ── Rendu 3D (synchrone : traces uniquement) ─────────────────────

    def _draw(self):
        if not self._gps_list:
            return

        self._cancel_fetch()
        self._draw_id   += 1
        current_id       = self._draw_id
        self._map_surface = None

        self._fig.clear()
        ax: Axes3D = self._fig.add_subplot(111, projection='3d')

        # ── Style sombre ─────────────────────────────────────────────
        self._fig.patch.set_facecolor('#1a2535')
        ax.set_facecolor('#1a2535')
        for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
            pane.set_facecolor('#1e2c3a')
            pane.set_edgecolor('#2c3e55')
        ax.tick_params(colors='#8ab4d8', labelsize=8)
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.label.set_color('#8ab4d8')
            axis.label.set_fontsize(9)
        ax.grid(True, color='#2c3e55', linewidth=0.5)

        # ── Référence commune ────────────────────────────────────────
        all_xs = np.concatenate([g.xs for g in self._gps_list])
        all_ys = np.concatenate([g.ys for g in self._gps_list])
        x_ref, y_ref = all_xs.mean(), all_ys.mean()

        all_zs  = np.concatenate([_fill_none(g.alts) for g in self._gps_list])
        z_span  = all_zs.max() - all_zs.min()
        z_floor = all_zs.min() - max(z_span * 0.1, 5.0)

        self._x_ref   = x_ref
        self._y_ref   = y_ref
        self._z_floor = z_floor

        legend_handles = []

        for i, gps in enumerate(self._gps_list):
            color = _TRACK_PALETTE[i % len(_TRACK_PALETTE)]
            xs = gps.xs - x_ref
            ys = gps.ys - y_ref
            zs = _fill_none(gps.alts)

            if self._color_mode == 'flat':
                ax.plot(xs, ys, zs, color=color, linewidth=1.6,
                        alpha=0.9, zorder=3)
            else:
                vals = (zs if self._color_mode == 'altitude'
                        else _fill_none(gps.speeds))
                cmap = (_CMAP_ALT if self._color_mode == 'altitude'
                        else _CMAP_SPD)
                vmin, vmax = vals.min(), vals.max()
                norm = mcolors.Normalize(
                    vmin=vmin, vmax=vmax if vmax > vmin else vmin + 1)
                segs = _make_segments(xs, ys, zs)
                lc = Line3DCollection(segs, cmap=cmap, norm=norm,
                                      linewidth=1.6, alpha=0.9)
                lc.set_array(vals[:-1])
                ax.add_collection3d(lc)

            ax.scatter([xs[0]],  [ys[0]],  [zs[0]],
                       color=color, s=55, marker='o', zorder=5,
                       edgecolors='white', linewidths=1.2, depthshade=False)
            ax.scatter([xs[-1]], [ys[-1]], [zs[-1]],
                       color=color, s=55, marker='s', zorder=5,
                       edgecolors='white', linewidths=1.2, depthshade=False)

            legend_handles.append(
                Line2D([0], [0], color=color, linewidth=2, label=gps.filename))

        # ── Colorbar (modes altitude / vitesse) ──────────────────────
        if self._color_mode != 'flat':
            all_vals = np.concatenate([
                _fill_none(g.alts if self._color_mode == 'altitude' else g.speeds)
                for g in self._gps_list
            ])
            cmap  = _CMAP_ALT if self._color_mode == 'altitude' else _CMAP_SPD
            label = 'Altitude (m)' if self._color_mode == 'altitude' else 'Vitesse (km/h)'
            sm = matplotlib.cm.ScalarMappable(
                cmap=cmap,
                norm=mcolors.Normalize(all_vals.min(), all_vals.max()))
            sm.set_array([])
            cb = self._fig.colorbar(sm, ax=ax, shrink=0.55, pad=0.08,
                                    orientation='vertical')
            cb.set_label(label, color='#8ab4d8', fontsize=9)
            cb.ax.yaxis.set_tick_params(color='#8ab4d8', labelsize=8)
            for t in cb.ax.get_yticklabels():
                t.set_color('#8ab4d8')

        # ── Légende ──────────────────────────────────────────────────
        if legend_handles:
            leg = ax.legend(handles=legend_handles,
                            loc='upper left', fontsize=8,
                            facecolor='#1e2c3a', edgecolor='#2c3e55',
                            labelcolor='#c8d8e8')
            leg.get_frame().set_alpha(0.85)

        # ── Axes labels ──────────────────────────────────────────────
        ax.set_xlabel('Est (m)',      fontsize=9, labelpad=6)
        ax.set_ylabel('Nord (m)',     fontsize=9, labelpad=6)
        ax.set_zlabel('Altitude (m)', fontsize=9, labelpad=6)

        ax.view_init(elev=25, azim=-60)
        self._fig.tight_layout(pad=1.0)
        self._canvas.draw()

        # ── Lancement du téléchargement en arrière-plan ──────────────
        if self._show_map:
            span = max(all_xs.max() - all_xs.min(),
                       all_ys.max() - all_ys.min())
            pad  = max(span * 0.08, 200.0)
            self._tile_fetcher = _TileFetcher(
                all_xs.min() - pad, all_ys.min() - pad,
                all_xs.max() + pad, all_ys.max() + pad,
                current_id,
            )
            self._tile_fetcher.tile_ready.connect(self._on_tiles_ready)
            self._tile_fetcher.start()

    # ── Réception des tuiles (thread principal via signal Qt) ─────────

    def _on_tiles_ready(self, img, ext, draw_id: int):
        if draw_id != self._draw_id or img is None or not self._fig.axes:
            return

        ax = self._fig.axes[0]

        # Réduction à 64 px max : 4 096 polygones suffisent pour un fond de carte
        h, w = img.shape[:2]
        max_px = 64
        if max(h, w) > max_px:
            scale   = max_px / max(h, w)
            nh, nw  = max(1, int(h * scale)), max(1, int(w * scale))
            row_idx = np.linspace(0, h - 1, nh).astype(int)
            col_idx = np.linspace(0, w - 1, nw).astype(int)
            img = img[np.ix_(row_idx, col_idx)]

        img_rgba = img.astype(float) / 255.0
        img_rgba = img_rgba[::-1]   # flip : ligne 0 → sud

        h, w = img_rgba.shape[:2]
        xv = np.linspace(ext[0] - self._x_ref, ext[1] - self._x_ref, w + 1)
        yv = np.linspace(ext[2] - self._y_ref, ext[3] - self._y_ref, h + 1)
        X, Y = np.meshgrid(xv, yv)
        Z    = np.full_like(X, self._z_floor)

        ax.zaxis.pane.set_facecolor((0, 0, 0, 0))
        ax.zaxis.pane.set_edgecolor((0, 0, 0, 0))

        self._map_surface = ax.plot_surface(X, Y, Z, facecolors=img_rgba,
                                             shade=False, antialiased=False,
                                             rstride=1, cstride=1)
        self._canvas.draw()

    def _reset_view(self):
        if self._fig.axes:
            ax = self._fig.axes[0]
            ax.view_init(elev=25, azim=-60)
            self._canvas.draw()
