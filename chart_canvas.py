"""
chart_canvas.py — ChartCanvas (profil altimétrique / vitesse)
"""

import numpy as np
import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSizePolicy

# ── Couleurs locales ─────────────────────────────────────────────────
C_ALT    = '#1a6fbf'
C_SPD    = '#27ae60'
C_CURSOR = '#e74c3c'


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
