"""
map_live.py — LiveTrackMixin : affichage de la trace GPS reçue en temps réel
              (LoRa Live). La trace s'allonge au fil des réceptions, le
              marqueur glisse vers chaque nouvelle position en pointant dans
              le sens de la marche, une étiquette donne vitesse et heure, et
              la carte suit la position (désactivé dès que l'utilisateur
              déplace la carte à la main).
              Extrait de map_canvas.py (MapCanvas hérite de ce mixin).

Animation par « blitting » : un rendu matplotlib complet de la carte coûte
~0,1 s, trop pour 25 images/s. Les artistes live sont donc marqués
`animated=True` (exclus des rendus complets) ; à chaque rendu complet on
mémorise l'image de la carte (_live_on_draw), puis chaque image de
l'animation se contente de restaurer ce fond, dessiner les artistes live et
copier le résultat à l'écran (_live_blit).
"""

import math
import time

from matplotlib.markers import MarkerStyle
from matplotlib.path import Path as MplPath
from matplotlib.transforms import Affine2D
from PyQt5.QtCore import QTimer

from gps_nmea import _webmerc_to_latlon

_GLIDE_S        = 1.0    # durée du glissement vers la nouvelle position (s)
_FRAME_MS       = 40     # ~25 images/s pendant le glissement
_MIN_MOVE_M     = 5.0    # déplacement minimal pour mettre à jour le cap (bruit GPS)
_FOLLOW_MARGIN  = 0.2    # suivi : recentre quand le point sort des 60 % centraux
_START_RADIUS_M = 500    # vue initiale autour du premier point (rayon, m)
_MAX_START_SPAN = 5000   # au premier point, zoome si la vue est plus large (m)

# Flèche pointant vers le haut (orientée ensuite selon le cap)
_ARROW = MplPath(
    [(0, 1), (0.62, -0.75), (0, -0.35), (-0.62, -0.75), (0, 1)],
    [MplPath.MOVETO, MplPath.LINETO, MplPath.LINETO, MplPath.LINETO,
     MplPath.CLOSEPOLY])


class LiveTrackMixin:
    """Trace LoRa Live de MapCanvas.

    Mixin pour MapCanvas — s'appuie sur ax, fig, draw_idle, copy_from_bbox /
    restore_region / blit (FigureCanvasQTAgg), _tile_timer, _request_tiles,
    _redraw_photos / _redraw_notes et le signal live_follow_changed.
    """

    def _init_live(self):
        self._live_line  = None    # Line2D de la trace en cours
        self._live_head  = None    # marqueur de la position courante
        self._live_label = None    # étiquette vitesse / heure
        self._live_xs: list = []
        self._live_ys: list = []
        self._live_color   = '#e67e22'
        self._live_active  = False
        self._live_follow  = True
        self._live_anim    = None  # (x0, y0, x1, y1, t0) pendant un glissement
        self._live_pos     = None  # position affichée du marqueur (x, y)
        self._live_bg      = None  # (image de fond, clé de vue) pour le blitting
        self._live_timer = QTimer(self, interval=_FRAME_MS)
        self._live_timer.timeout.connect(self._live_frame)
        self.mpl_connect('draw_event', self._live_on_draw)

    # ── API (MainWindow) ─────────────────────────────────────────────

    def start_live_track(self, color: str = '#e67e22'):
        """Prépare l'overlay live. Les artistes sont créés au premier point si la carte est vide."""
        self._stop_live_artists()
        self._live_color  = color
        self._live_xs     = []
        self._live_ys     = []
        self._live_active = True
        self.set_live_follow(True)
        if self._default_lim is not None:
            self._create_live_artists()
            self.draw_idle()

    def append_live_point(self, x_m: float, y_m: float,
                          speed_kmh: float | None = None, time_str: str = ''):
        """Ajoute un point GPS reçu en temps réel (thread principal, via signal Qt)."""
        self._live_xs.append(x_m)
        self._live_ys.append(y_m)
        if self._live_line is None:
            self._init_live_map(x_m, y_m)
        elif len(self._live_xs) == 1 and self._live_follow:
            # Carte déjà affichée (trace chargée, vue régionale…) : zoome sur
            # la position reçue, sinon le déplacement serait imperceptible
            xl = self.ax.get_xlim()
            if xl[1] - xl[0] > _MAX_START_SPAN:
                self.ax.set_xlim(x_m - _START_RADIUS_M, x_m + _START_RADIUS_M)
                self.ax.set_ylim(y_m - _START_RADIUS_M, y_m + _START_RADIUS_M)
                self._reload_tiles()

        self._live_update_heading()
        parts = [f'{speed_kmh:.1f} km/h'] if speed_kmh is not None else []
        if time_str:
            parts.append(time_str)
        self._live_label.set_text('  ·  '.join(parts))
        self._live_label.set_visible(bool(parts))

        if self._live_follow:
            self._live_keep_in_view(x_m, y_m)

        start = self._live_pos
        if start is None or start == (x_m, y_m):
            self._live_anim = None
            self._live_pos  = (x_m, y_m)
        else:
            self._live_anim = (start[0], start[1], x_m, y_m, time.monotonic())
            self._live_timer.start()
        self._live_update_artists()
        self._live_blit()

    def set_live_follow(self, on: bool):
        """Active / désactive le suivi automatique de la position live."""
        if on == self._live_follow:
            return
        self._live_follow = on
        self.live_follow_changed.emit(on)
        if on and self._live_xs and self._live_line is not None:
            self._live_center_on(self._live_xs[-1], self._live_ys[-1])

    def stop_live_track(self):
        """Retire les artistes live de la carte (les traces chargées restent visibles)."""
        self._stop_live_artists()
        self._live_xs = []
        self._live_ys = []
        self._live_active = False
        self.draw_idle()

    # ── Création / suppression des artistes ──────────────────────────

    def _create_live_artists(self):
        c = self._live_color
        self._live_line, = self.ax.plot(
            [], [], color=c, linewidth=2.5, zorder=5, animated=True,
            solid_capstyle='round', solid_joinstyle='round',
            label='◎ LoRa Live')
        self._live_head, = self.ax.plot(
            [], [], linestyle='none', marker='o', markersize=14, color=c,
            markeredgecolor='white', markeredgewidth=2, zorder=10,
            animated=True)
        self._live_label = self.ax.annotate(
            '', xy=(0, 0), xytext=(14, 12), textcoords='offset points',
            fontsize=8, color='#222', zorder=11, animated=True,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                      alpha=0.88, edgecolor=c, linewidth=0.8))
        self._live_label.set_visible(False)
        self.ax.legend(loc='upper left', fontsize=9,
                       framealpha=0.85, fancybox=True)

    def _init_live_map(self, x_m: float, y_m: float):
        """Configure la vue centrée sur le premier point live (carte était vide)."""
        margin = _START_RADIUS_M
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

        self._create_live_artists()

        # Redessine les éventuelles annotations déjà chargées
        self._redraw_photos()
        self._redraw_notes()

        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        self._request_tiles()

    def _live_artists(self) -> list:
        return [a for a in (self._live_line, self._live_head, self._live_label)
                if a is not None]

    def _stop_live_artists(self):
        """Supprime proprement les artistes matplotlib de la trace live."""
        for art in self._live_artists():
            try:
                art.remove()
            except Exception:
                pass
        self._live_forget_artists()

    def _live_forget_artists(self):
        """Oublie les artistes live (déjà retirés, ex. après ax.cla())."""
        self._live_timer.stop()
        self._live_line = self._live_head = self._live_label = None
        self._live_anim = self._live_pos = self._live_bg = None

    # ── Cap, suivi, animation ────────────────────────────────────────

    def _live_update_heading(self):
        """Oriente la flèche selon le dernier déplacement significatif."""
        if len(self._live_xs) < 2:
            return
        x0, y0 = self._live_xs[-2], self._live_ys[-2]
        x1, y1 = self._live_xs[-1], self._live_ys[-1]
        # Web Mercator dilate les distances de 1/cos(lat) : ramène en mètres réels
        lat = _webmerc_to_latlon(x1, y1)[0]
        if math.hypot(x1 - x0, y1 - y0) * math.cos(math.radians(lat)) < _MIN_MOVE_M:
            return                                  # immobile : cap inchangé
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0))   # depuis l'est, sens trigo
        self._live_head.set_marker(
            MarkerStyle(_ARROW, transform=Affine2D().rotate_deg(angle - 90)))
        self._live_head.set_markersize(20)

    def _live_keep_in_view(self, x: float, y: float):
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        mx = (xl[1] - xl[0]) * _FOLLOW_MARGIN
        my = (yl[1] - yl[0]) * _FOLLOW_MARGIN
        if not (xl[0] + mx <= x <= xl[1] - mx and yl[0] + my <= y <= yl[1] - my):
            self._live_center_on(x, y)

    def _live_center_on(self, x: float, y: float):
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        hw, hh = (xl[1] - xl[0]) / 2, (yl[1] - yl[0]) / 2
        self.ax.set_xlim(x - hw, x + hw)
        self.ax.set_ylim(y - hh, y + hh)
        self._tile_timer.start()
        self.draw_idle()

    def _live_user_panned(self):
        """L'utilisateur a déplacé la carte : il veut regarder ailleurs."""
        if self._live_active and self._live_follow:
            self.set_live_follow(False)

    def _live_frame(self):
        if self._live_anim is None:
            self._live_timer.stop()
            return
        self._live_update_artists()
        self._live_blit()

    def _live_update_artists(self):
        if self._live_line is None or not self._live_xs:
            return
        if self._live_anim is not None:
            x0, y0, x1, y1, t0 = self._live_anim
            t = min(1.0, (time.monotonic() - t0) / _GLIDE_S)
            e = t * t * (3 - 2 * t)                  # accélère puis ralentit
            self._live_pos = (x0 + (x1 - x0) * e, y0 + (y1 - y0) * e)
            if t >= 1.0:
                self._live_anim = None
                self._live_timer.stop()
        px, py = self._live_pos
        if self._live_anim is not None:
            # la trace s'allonge avec le marqueur
            self._live_line.set_data(self._live_xs[:-1] + [px],
                                     self._live_ys[:-1] + [py])
        else:
            self._live_line.set_data(self._live_xs, self._live_ys)
        self._live_head.set_data([px], [py])
        self._live_label.xy = (px, py)

    # ── Blitting ─────────────────────────────────────────────────────

    def _live_view_key(self):
        bb = self.fig.bbox
        return (self.ax.get_xlim(), self.ax.get_ylim(), bb.width, bb.height)

    def _live_on_draw(self, event):
        """Après chaque rendu complet : mémorise le fond, dessine les artistes live."""
        if self._live_line is None:
            self._live_bg = None
            return
        self._live_bg = (self.copy_from_bbox(self.fig.bbox), self._live_view_key())
        for art in self._live_artists():
            self.ax.draw_artist(art)

    def _live_blit(self):
        """Redessine uniquement les artistes live sur le fond mémorisé."""
        if self._live_line is None:
            return
        if self._live_bg is None or self._live_bg[1] != self._live_view_key():
            self.draw_idle()                         # vue changée : rendu complet
            return
        self.restore_region(self._live_bg[0])
        for art in self._live_artists():
            self.ax.draw_artist(art)
        self.blit(self.fig.bbox)
