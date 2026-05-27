"""
view_3d.py — Fenêtre de visualisation 3D de la trace GPS
           (matplotlib Axes3D, aucune dépendance supplémentaire)
"""

import numpy as np
import matplotlib
import matplotlib.colors as mcolors
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d import Axes3D           # noqa: F401 — enregistrement side-effect
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QToolBar, QAction,
    QLabel, QComboBox, QSizePolicy, QWidget,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont

from gps_nmea import GPSData
from map_canvas import _TRACK_PALETTE, _CMAP_ALT, _CMAP_SPD


# ── Helpers ───────────────────────────────────────────────────────────

def _fill_none(values: list, dtype=float) -> np.ndarray:
    """Convertit une liste avec None en ndarray, NaN remplacé par la médiane."""
    arr = np.array([v if v is not None else np.nan for v in values], dtype=dtype)
    if np.all(np.isnan(arr)):
        return np.zeros(len(arr), dtype=dtype)
    median = float(np.nanmedian(arr))
    arr = np.where(np.isnan(arr), median, arr)
    return arr


def _make_segments(xs, ys, zs) -> np.ndarray:
    """Retourne un tableau (N-1, 2, 3) de segments consécutifs."""
    pts = np.stack([xs, ys, zs], axis=1)          # (N, 3)
    return np.stack([pts[:-1], pts[1:]], axis=1)   # (N-1, 2, 3)


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

        self._gps_list   = gps_list
        self._color_mode = 'flat'   # 'flat' | 'altitude' | 'speed'

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

        act_reset = QAction('⌂  Réinitialiser la vue', self)
        act_reset.setToolTip('Revenir à l\'angle de vue par défaut')
        act_reset.triggered.connect(self._reset_view)
        tb.addAction(act_reset)

        root.addWidget(tb)

        # ── Canvas matplotlib ────────────────────────────────────────
        self._fig    = Figure(facecolor='#1a2535')
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._canvas)

        self._draw()

    # ── Slots ────────────────────────────────────────────────────────

    def _on_color_mode(self, idx: int):
        self._color_mode = ('flat', 'altitude', 'speed')[idx]
        self._draw()

    def refresh(self, gps_list: list):
        """Met à jour les données et redessine."""
        self._gps_list = gps_list
        self._draw()

    # ── Rendu 3D ─────────────────────────────────────────────────────

    def _draw(self):
        if not self._gps_list:
            return

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

        legend_handles = []

        for i, gps in enumerate(self._gps_list):
            color = _TRACK_PALETTE[i % len(_TRACK_PALETTE)]
            xs  = gps.xs - x_ref
            ys  = gps.ys - y_ref
            zs  = _fill_none(gps.alts)

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

            # Marqueurs départ (●) et arrivée (■)
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
            plt_ticks = cb.ax.get_yticklabels()
            for t in plt_ticks:
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

    def _reset_view(self):
        if self._fig.axes:
            ax = self._fig.axes[0]
            ax.view_init(elev=25, azim=-60)
            self._canvas.draw()
