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
    QDialog, QVBoxLayout, QHBoxLayout, QToolBar, QAction,
    QLabel, QComboBox, QSizePolicy, QPushButton, QSlider, QWidget,
)
from PyQt5.QtCore import Qt, QSize, QThread, QTimer, pyqtSignal

from gps_nmea import GPSData, _webmerc_to_latlon, WEB_MERC_R
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


# ── Worker : données SRTM pour les courbes 3D ────────────────────────

class _SrtmFetcher(QThread):
    """Calcule la grille d'altitude SRTM pour la bounding box des traces."""
    srtm_ready = pyqtSignal(object, object, object, int)  # lat_g, lon_g, elev_g, draw_id

    def __init__(self, lat_min, lat_max, lon_min, lon_max, draw_id: int):
        super().__init__()
        self._lat_min = lat_min
        self._lat_max = lat_max
        self._lon_min = lon_min
        self._lon_max = lon_max
        self._draw_id = draw_id
        self._cancel  = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            import srtm
        except ImportError:
            return
        try:
            data  = srtm.get_data()
            n     = 60
            lats  = np.linspace(self._lat_min, self._lat_max, n)
            lons  = np.linspace(self._lon_min, self._lon_max, n)
            elev  = np.full((n, n), np.nan)
            for i, lat in enumerate(lats):
                if self._cancel:
                    return
                for j, lon in enumerate(lons):
                    e = data.get_elevation(lat, lon)
                    if e is not None:
                        elev[i, j] = float(e)
            lon_g, lat_g = np.meshgrid(lons, lats)
            if not self._cancel:
                self.srtm_ready.emit(lat_g, lon_g, elev, self._draw_id)
        except Exception:
            pass


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
        self._show_contours = False
        self._res_px      = 64       # résolution max de la tuile OSM (px)
        self._draw_id     = 0
        self._tile_fetcher: '_TileFetcher | None' = None
        self._srtm_fetcher: '_SrtmFetcher | None' = None
        self._srtm_data   = None     # (lat_g, lon_g, elev_g) mis en cache
        self._map_surface = None     # référence au plot_surface OSM
        self._raw_img     = None     # image brute (non redimensionnée) pour changement de résolution
        self._raw_ext     = None
        # Mémorisés pour l'application différée des tuiles
        self._x_ref   = 0.0
        self._y_ref   = 0.0
        self._z_floor = 0.0

        # ── Animation ────────────────────────────────────────────────
        self._anim_index        = 0
        self._anim_playing      = False
        self._anim_speed        = 1
        self._anim_dots: list   = []
        self._anim_traces: list = []   # [(xs_rel, ys_rel, zs)] par trace
        self._anim_max_count    = 0
        self._scrub_was_playing = False
        self._anim_timer        = QTimer(self, interval=100)
        self._anim_timer.timeout.connect(self._anim_tick)

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

        lbl_res = QLabel('  Résolution :')
        lbl_res.setStyleSheet('font-size:12px; color:#555; padding:0 4px;')
        tb.addWidget(lbl_res)

        self._res_combo = QComboBox()
        self._res_combo.addItems(['Basse (64)', 'Moyenne (128)', 'Haute (256)'])
        self._res_combo.setCurrentIndex(0)
        self._res_combo.setFixedWidth(120)
        self._res_combo.setToolTip('Résolution du fond de carte OSM')
        self._res_combo.currentIndexChanged.connect(self._on_res_changed)
        tb.addWidget(self._res_combo)

        tb.addSeparator()

        self._act_contours = QAction('🏔  Courbes 3D', self)
        self._act_contours.setCheckable(True)
        self._act_contours.setChecked(False)
        self._act_contours.setToolTip(
            'Afficher les courbes de niveau SRTM en 3D\n'
            'Premier affichage : téléchargement des données SRTM')
        self._act_contours.triggered.connect(self._on_toggle_contours)
        tb.addAction(self._act_contours)

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

        # ── Barre de lecture 3D ──────────────────────────────────────
        root.addWidget(self._build_play_bar())

        # ── Barre de stats en bas ────────────────────────────────────
        self._lbl_stats = QLabel()
        self._lbl_stats.setStyleSheet(
            'background:#1e2d40; color:#9ab; font-size:11px;'
            ' padding:3px 10px; border-top:1px solid #2c3e55;')
        self._lbl_stats.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._lbl_stats.setFixedHeight(24)
        root.addWidget(self._lbl_stats)
        self._refresh_stats_label()

        # Masquer la carte pendant les interactions souris (rotation/pan)
        # pour que chaque frame soit calculée sans les polygones OSM
        self._canvas.mpl_connect('button_press_event',   self._on_rot_start)
        self._canvas.mpl_connect('button_release_event', self._on_rot_end)
        self._canvas.mpl_connect('scroll_event',         self._on_scroll)

        # Différer le rendu pour que la fenêtre s'affiche avant de bloquer
        QTimer.singleShot(0, self._draw)

    # ── Cycle de vie ─────────────────────────────────────────────────

    def closeEvent(self, event):
        self._anim_timer.stop()
        self._cancel_fetch()
        super().closeEvent(event)

    def _cancel_fetch(self):
        if self._tile_fetcher and self._tile_fetcher.isRunning():
            self._tile_fetcher.cancel()
            try:
                self._tile_fetcher.tile_ready.disconnect()
            except TypeError:
                pass
        if self._srtm_fetcher and self._srtm_fetcher.isRunning():
            self._srtm_fetcher.cancel()
            try:
                self._srtm_fetcher.srtm_ready.disconnect()
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

    def _on_scroll(self, event):
        """Zoom molette : redimensionne les limites des trois axes autour de leur centre."""
        if not self._fig.axes:
            return
        ax = self._fig.axes[0]
        factor = 0.85 if event.button == 'up' else 1.18
        for get_lim, set_lim in (
            (ax.get_xlim3d, ax.set_xlim3d),
            (ax.get_ylim3d, ax.set_ylim3d),
            (ax.get_zlim3d, ax.set_zlim3d),
        ):
            lo, hi = get_lim()
            mid    = (lo + hi) / 2
            half   = (hi - lo) / 2 * factor
            set_lim(mid - half, mid + half)
        self._canvas.draw_idle()

    # ── Slots ────────────────────────────────────────────────────────

    def _on_color_mode(self, idx: int):
        self._color_mode = ('flat', 'altitude', 'speed')[idx]
        self._draw()

    def _on_toggle_map(self, checked: bool):
        self._show_map = checked
        self._res_combo.setEnabled(checked)
        self._draw()

    def _on_res_changed(self, idx: int):
        self._res_px = (64, 128, 256)[idx]
        if self._raw_img is not None and self._fig.axes:
            if self._map_surface is not None:
                self._map_surface.remove()
                self._map_surface = None
            self._apply_map_tiles(self._raw_img, self._raw_ext)

    def refresh(self, gps_list: list):
        """Met à jour les données et redessine."""
        self._gps_list = gps_list
        self._srtm_data = None   # nouvelles traces → recalcul SRTM nécessaire
        self._refresh_stats_label()
        self._draw()

    def _refresh_stats_label(self):
        """Met à jour la barre de stats D+ / D− en bas de la fenêtre."""
        parts = []
        for gps in self._gps_list:
            s = f'{gps.filename}  —  {gps.total_dist:.0f} m'
            if gps.elev_gain is not None:
                s += f'  •  D+ {gps.elev_gain:.0f} m  D− {gps.elev_loss:.0f} m'
            if gps.alt_min is not None:
                s += f'  •  Alt {gps.alt_min:.0f}–{gps.alt_max:.0f} m'
            parts.append(s)
        self._lbl_stats.setText('     │     '.join(parts) if parts else '—')

    def _on_toggle_contours(self, checked: bool):
        self._show_contours = checked
        if checked:
            if self._srtm_data is not None:
                self._draw_3d_contours(*self._srtm_data)
            else:
                self._launch_srtm_fetch()
        else:
            self._draw()

    # ── Rendu 3D (synchrone : traces uniquement) ─────────────────────

    def _draw(self):
        if not self._gps_list:
            return

        self._anim_timer.stop()
        self._anim_playing = False
        self._anim_index   = 0
        self._anim_dots    = []
        self._anim_traces  = []

        self._cancel_fetch()
        self._draw_id    += 1
        current_id        = self._draw_id
        self._map_surface = None
        self._raw_img     = None
        self._raw_ext     = None

        self._fig.clear()
        ax: Axes3D = self._fig.add_subplot(111, projection='3d')

        # Empêcher la caméra de passer sous le plan horizontal :
        # _on_move appelle view_init() — on intercepte ici pour clamer elev >= 0.
        _orig_vi = ax.view_init
        def _clamped_view_init(elev=None, azim=None, **kw):
            if elev is not None:
                elev = max(0.0, elev)
            _orig_vi(elev=elev, azim=azim, **kw)
        ax.view_init = _clamped_view_init

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

        # ── Points animés (un par trace) ──────────────────────────────
        max_count = max(g.count for g in self._gps_list)
        self._anim_max_count = max_count
        for i, gps in enumerate(self._gps_list):
            color  = _TRACK_PALETTE[i % len(_TRACK_PALETTE)]
            xs_rel = gps.xs - x_ref
            ys_rel = gps.ys - y_ref
            zs     = _fill_none(gps.alts)
            self._anim_traces.append((xs_rel, ys_rel, zs))
            dot = ax.scatter([float(xs_rel[0])], [float(ys_rel[0])], [float(zs[0])],
                             color='white', s=80, marker='o',
                             edgecolors=color, linewidths=2.5,
                             depthshade=False, zorder=6)
            self._anim_dots.append(dot)

        # ── Init scrubber ─────────────────────────────────────────────
        self._anim_btn.blockSignals(True)
        self._anim_btn.setChecked(False)
        self._anim_btn.setText('▶  Animer')
        self._anim_btn.blockSignals(False)
        self._anim_scrubber.blockSignals(True)
        self._anim_scrubber.setRange(0, max_count - 1)
        self._anim_scrubber.setValue(0)
        self._anim_scrubber.blockSignals(False)
        self._anim_lbl.setText(f'point 1 / {max_count}')

        # ── Courbes de niveau 3D ─────────────────────────────────────
        if self._show_contours:
            if self._srtm_data is not None:
                self._draw_3d_contours(*self._srtm_data)
            else:
                self._launch_srtm_fetch()

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
        self._raw_img = img   # conservé pour le changement de résolution à chaud
        self._raw_ext = ext
        self._apply_map_tiles(img, ext)

    def _apply_map_tiles(self, img: np.ndarray, ext: tuple):
        """Redimensionne img à self._res_px et l'affiche comme plan OSM."""
        if not self._fig.axes:
            return
        ax = self._fig.axes[0]

        h, w = img.shape[:2]
        if max(h, w) > self._res_px:
            scale   = self._res_px / max(h, w)
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

    # ── Courbes de niveau 3D ─────────────────────────────────────────

    def _launch_srtm_fetch(self):
        """Calcule la bounding box des traces et lance le worker SRTM."""
        if not self._gps_list:
            return
        all_xs = np.concatenate([g.xs for g in self._gps_list])
        all_ys = np.concatenate([g.ys for g in self._gps_list])
        pad_x  = (all_xs.max() - all_xs.min()) * 0.15
        pad_y  = (all_ys.max() - all_ys.min()) * 0.15
        lat_min, lon_min = _webmerc_to_latlon(all_xs.min() - pad_x,
                                               all_ys.min() - pad_y)
        lat_max, lon_max = _webmerc_to_latlon(all_xs.max() + pad_x,
                                               all_ys.max() + pad_y)
        if self._srtm_fetcher and self._srtm_fetcher.isRunning():
            self._srtm_fetcher.cancel()
        self._srtm_fetcher = _SrtmFetcher(
            lat_min, lat_max, lon_min, lon_max, self._draw_id)
        self._srtm_fetcher.srtm_ready.connect(self._on_srtm_ready)
        self._srtm_fetcher.start()

    def _on_srtm_ready(self, lat_g, lon_g, elev_g, draw_id: int):
        if draw_id != self._draw_id or not self._show_contours:
            return
        self._srtm_data = (lat_g, lon_g, elev_g)
        self._draw_3d_contours(lat_g, lon_g, elev_g)

    def _draw_3d_contours(self, lat_g, lon_g, elev_g):
        """Dessine les courbes de niveau en 3D à leur altitude réelle."""
        if not self._fig.axes:
            return
        ax = self._fig.axes[0]

        # Conversion lat/lon → Web Mercator centré sur x_ref/y_ref
        x_g = np.radians(lon_g) * WEB_MERC_R - self._x_ref
        y_g = (WEB_MERC_R * np.log(
                   np.tan(np.pi / 4 + np.radians(lat_g) / 2))
               - self._y_ref)

        # Remplacer les NaN par la médiane locale
        valid = elev_g[~np.isnan(elev_g)]
        if valid.size == 0:
            return
        e_min, e_max = float(valid.min()), float(valid.max())
        if np.isnan(elev_g).any():
            elev_g = elev_g.copy()
            elev_g[np.isnan(elev_g)] = float(np.nanmedian(elev_g))

        # Intervalle : ~12 niveaux, arrondi à 10 m
        e_range = e_max - e_min
        interval = max(10, round(e_range / 12 / 10) * 10)
        first  = int(np.ceil(e_min / interval)) * interval
        levels = list(range(first, int(e_max) + interval, interval))
        if not levels:
            return
        major_levels = [l for l in levels if l % (interval * 4) == 0]

        # Courbes mineures
        ax.contour3D(x_g, y_g, elev_g,
                     levels=levels,
                     colors=['#8B6914'],
                     linewidths=0.4,
                     alpha=0.50)

        # Courbes majeures + étiquettes Z
        if major_levels:
            cs = ax.contour3D(x_g, y_g, elev_g,
                              levels=major_levels,
                              colors=['#5C3D0A'],
                              linewidths=0.9,
                              alpha=0.80)
            ax.clabel(cs, fmt='%d m', fontsize=6, colors=['#3E2800'])

        self._canvas.draw_idle()

    def _reset_view(self):
        if self._fig.axes:
            ax = self._fig.axes[0]
            ax.view_init(elev=25, azim=-60)
            self._canvas.draw()

    # ── Barre de lecture ─────────────────────────────────────────────

    def _build_play_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            'QWidget { background:#1e2d40; border-top:1px solid #2c3e55; }'
            'QPushButton { background:#2c3e55; color:#cde; border:none;'
            '  border-radius:4px; padding:3px 10px; font-size:12px; }'
            'QPushButton:hover { background:#3d5a80; }'
            'QPushButton:checked { background:#1a6fbf; color:white; }'
            'QLabel { background:transparent; color:#9ab; font-size:11px; }'
            'QComboBox { background:#2c3e55; color:#cde; border:none;'
            '  border-radius:4px; padding:2px 6px; font-size:11px; }'
            'QSlider::groove:horizontal { height:4px; background:#2c3e55;'
            '  border-radius:2px; }'
            'QSlider::sub-page:horizontal { background:#1a6fbf; border-radius:2px; }'
            'QSlider::handle:horizontal { width:12px; height:12px; margin:-4px 0;'
            '  background:#4fa3e0; border-radius:6px; }'
        )
        bar.setFixedHeight(56)

        outer = QVBoxLayout(bar)
        outer.setContentsMargins(8, 3, 8, 2)
        outer.setSpacing(2)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)

        btn_reset = QPushButton('⏮')
        btn_reset.setFixedWidth(30)
        btn_reset.setToolTip('Revenir au début de la trace')
        btn_reset.clicked.connect(self._anim_reset)
        ctrl.addWidget(btn_reset)

        self._anim_btn = QPushButton('▶  Animer')
        self._anim_btn.setCheckable(True)
        self._anim_btn.setFixedWidth(100)
        self._anim_btn.setToolTip("Démarrer / mettre en pause l'animation")
        self._anim_btn.toggled.connect(self._anim_toggle)
        ctrl.addWidget(self._anim_btn)

        self._anim_lbl = QLabel('point — / —')
        ctrl.addWidget(self._anim_lbl, 1)

        ctrl.addWidget(QLabel('Vitesse :'))

        self._anim_speed_combo = QComboBox()
        self._anim_speed_combo.addItems(['×1', '×2', '×5', '×10'])
        self._anim_speed_combo.setFixedWidth(60)
        self._anim_speed_combo.setToolTip('Points avancés par tick de 100 ms')
        self._anim_speed_combo.currentIndexChanged.connect(
            lambda idx: setattr(self, '_anim_speed', [1, 2, 5, 10][idx]))
        ctrl.addWidget(self._anim_speed_combo)

        outer.addLayout(ctrl)

        self._anim_scrubber = QSlider(Qt.Horizontal)
        self._anim_scrubber.setRange(0, 0)
        self._anim_scrubber.setValue(0)
        self._anim_scrubber.setToolTip('Glisser pour se positionner dans la trace')
        self._anim_scrubber.sliderPressed.connect(self._on_scrub_press)
        self._anim_scrubber.sliderMoved.connect(self._anim_seek)
        self._anim_scrubber.sliderReleased.connect(self._on_scrub_release)
        outer.addWidget(self._anim_scrubber)

        return bar

    # ── Slots d'animation ────────────────────────────────────────────

    def _anim_toggle(self, checked: bool):
        if checked:
            if not self._anim_dots or self._anim_max_count == 0:
                self._anim_btn.blockSignals(True)
                self._anim_btn.setChecked(False)
                self._anim_btn.blockSignals(False)
                return
            # Si on est déjà à la fin, rebobiner avant de lancer
            if self._anim_index >= self._anim_max_count - 1:
                self._anim_index = 0
                self._update_anim_dots(0)
                self._anim_scrubber.blockSignals(True)
                self._anim_scrubber.setValue(0)
                self._anim_scrubber.blockSignals(False)
            self._anim_btn.setText('⏸  Pause')
            self._anim_playing = True
            self._anim_timer.start()
        else:
            self._anim_btn.setText('▶  Animer')
            self._anim_playing = False
            self._anim_timer.stop()

    def _anim_reset(self):
        self._anim_timer.stop()
        self._anim_playing = False
        self._anim_btn.blockSignals(True)
        self._anim_btn.setChecked(False)
        self._anim_btn.setText('▶  Animer')
        self._anim_btn.blockSignals(False)
        self._anim_index = 0
        self._update_anim_dots(0)
        self._anim_scrubber.blockSignals(True)
        self._anim_scrubber.setValue(0)
        self._anim_scrubber.blockSignals(False)
        if self._anim_max_count:
            self._anim_lbl.setText(f'point 1 / {self._anim_max_count}')

    def _anim_tick(self):
        if not self._anim_dots or self._anim_max_count == 0:
            self._anim_timer.stop()
            return
        next_idx = self._anim_index + self._anim_speed
        if next_idx >= self._anim_max_count:
            next_idx = self._anim_max_count - 1
            self._anim_timer.stop()
            self._anim_playing = False
            self._anim_btn.blockSignals(True)
            self._anim_btn.setChecked(False)
            self._anim_btn.setText('▶  Animer')
            self._anim_btn.blockSignals(False)
        self._anim_index = next_idx
        self._update_anim_dots(next_idx)
        self._anim_scrubber.blockSignals(True)
        self._anim_scrubber.setValue(next_idx)
        self._anim_scrubber.blockSignals(False)
        self._anim_lbl.setText(f'point {next_idx + 1} / {self._anim_max_count}')

    def _anim_seek(self, value: int):
        self._anim_index = value
        self._update_anim_dots(value)
        self._anim_lbl.setText(f'point {value + 1} / {self._anim_max_count}')

    def _on_scrub_press(self):
        self._scrub_was_playing = self._anim_playing
        if self._anim_playing:
            self._anim_timer.stop()

    def _on_scrub_release(self):
        if self._scrub_was_playing:
            self._anim_timer.start()

    def _update_anim_dots(self, index: int):
        if not self._fig.axes or not self._anim_dots:
            return
        for (xs_rel, ys_rel, zs), dot in zip(self._anim_traces, self._anim_dots):
            idx = min(index, len(xs_rel) - 1)
            dot._offsets3d = ([float(xs_rel[idx])], [float(ys_rel[idx])], [float(zs[idx])])
        self._canvas.draw_idle()
