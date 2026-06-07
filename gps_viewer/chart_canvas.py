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


def _fmt_dist(d: float) -> str:
    return f'{d / 1000:.1f} km' if d >= 1000 else f'{d:.0f} m'


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
        self._vline             = None
        self._dist_arr          = None
        self._total_dist        = None
        self._cursor_annot      = None
        self._show_cursor_info  = True
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

    def load(self, distances: list, data: list, ylabel: str, info: str = ''):
        self._dist_arr     = np.array(distances)
        self._total_dist   = float(distances[-1]) if distances else None
        self._cursor_annot = None  # ax.cla() invalide l'ancien artist
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

        if info:
            self.ax.text(0.98, 0.96, info,
                         transform=self.ax.transAxes,
                         ha='right', va='top', fontsize=9, color='#555',
                         bbox=dict(boxstyle='round,pad=0.35',
                                   facecolor='#f0f4f8',
                                   edgecolor='#ccc', alpha=0.88),
                         zorder=6)

        self._vline = self.ax.axvline(
            x=0, color=C_CURSOR, linewidth=1.6,
            linestyle='--', visible=False, zorder=5)

        self.fig.tight_layout(pad=0.8)
        self.draw()

    def load_multi(self, series: list, ylabel: str):
        """Superpose plusieurs traces sur le même graphique.
        series : list of (distances, data, label, color)
        """
        self._dist_arr     = None
        self._vline        = None
        self._total_dist   = None
        self._cursor_annot = None
        self.ax.cla()
        self._style_ax()
        self.ax.set_ylabel(ylabel, fontsize=9, color='#888', labelpad=3)

        all_val_min, all_val_max, all_dist_max = float('inf'), float('-inf'), 0.0
        for distances, data, label, color in series:
            valid = [(d, v) for d, v in zip(distances, data) if v is not None]
            if not valid:
                continue
            ds, vs = zip(*valid)
            ds, vs = np.array(ds), np.array(vs)
            all_dist_max = max(all_dist_max, float(ds[-1]))
            all_val_min  = min(all_val_min,  float(vs.min()))
            all_val_max  = max(all_val_max,  float(vs.max()))
            self.ax.fill_between(ds, vs, alpha=0.10, color=color, zorder=1)
            self.ax.plot(ds, vs, color=color, linewidth=1.8, label=label,
                         zorder=2, solid_capstyle='round')

        if all_val_min < float('inf'):
            pad = max(0.5, (all_val_max - all_val_min) * 0.18)
            self.ax.set_ylim(all_val_min - pad, all_val_max + pad)
        if all_dist_max > 0:
            self.ax.set_xlim(0, all_dist_max)

        handles, labels = self.ax.get_legend_handles_labels()
        if handles:
            self.ax.legend(handles, labels, fontsize=8, loc='best',
                           framealpha=0.85, edgecolor='#ddd')

        self.fig.tight_layout(pad=0.8)
        self.draw()

    def clear(self):
        self._dist_arr     = None
        self._vline        = None
        self._total_dist   = None
        self._cursor_annot = None
        self._draw_empty()

    def update_cursor(self, index):
        if self._vline is None or self._dist_arr is None:
            return
        if index is not None and 0 <= index < len(self._dist_arr):
            x = float(self._dist_arr[index])
            self._vline.set_xdata([x])
            self._vline.set_visible(True)
            if self._total_dist is not None:
                remaining = self._total_dist - x
                txt = f'↑ {_fmt_dist(x)}   ↓ {_fmt_dist(remaining)}'
                ha  = 'left' if index < len(self._dist_arr) * 0.6 else 'right'
                if self._cursor_annot is None:
                    self._cursor_annot = self.ax.text(
                        x, 0.97, txt,
                        transform=self.ax.get_xaxis_transform(),
                        ha=ha, va='top', fontsize=8, color='#444',
                        bbox=dict(boxstyle='round,pad=0.3',
                                  facecolor='#fff8e8', edgecolor='#e0c070',
                                  alpha=0.92),
                        zorder=6)
                    self._cursor_annot.set_visible(self._show_cursor_info)
                else:
                    self._cursor_annot.set_x(x)
                    self._cursor_annot.set_text(txt)
                    self._cursor_annot.set_ha(ha)
                    self._cursor_annot.set_visible(self._show_cursor_info)
        else:
            self._vline.set_visible(False)
            if self._cursor_annot is not None:
                self._cursor_annot.set_visible(False)
        self.draw_idle()

    def set_show_cursor_info(self, visible: bool):
        """Affiche ou masque l'annotation distance parcouru/restant."""
        self._show_cursor_info = visible
        if self._cursor_annot is not None:
            self._cursor_annot.set_visible(
                visible and self._vline is not None
                and self._vline.get_visible())
            self.draw_idle()

    def _mouse_move(self, event):
        if event.inaxes != self.ax or self._dist_arr is None:
            return
        idx = int(np.argmin(np.abs(self._dist_arr - event.xdata)))
        self._on_hover(idx)
