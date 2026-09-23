"""
map_tools.py — Outils interactifs de la carte : mesure de distance,
               annotations photo (avec indicateur de direction « œil »)
               et annotations note.
               Extrait de map_canvas.py (MapCanvas hérite de ces mixins)
               pour garder ce dernier plus lisible.
"""

import math

import numpy as np
from PIL import Image as PilImage
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

from PyQt5.QtCore import Qt

from gps_nmea import _webmerc_to_latlon, haversine_m


# Les mixins ci-dessous s'appuient sur des attributs, signaux et méthodes
# définis dans map_canvas.MapCanvas (ax, draw_idle, setCursor, signaux
# measure_updated / photo_eye_changed, état _meas_* / _photo_* / _note_*…).
# Les signaux Qt restent déclarés sur MapCanvas : pyqtSignal ne fonctionne
# que sur une sous-classe de QObject.


class MeasureToolMixin:
    """Mesure de distance clic-à-clic (Ctrl+D)."""

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

    @staticmethod
    def _meas_dist_m(x0: float, y0: float, x1: float, y1: float) -> float:
        lat0, lon0 = _webmerc_to_latlon(x0, y0)
        lat1, lon1 = _webmerc_to_latlon(x1, y1)
        return haversine_m(lat0, lon0, lat1, lon1)

    @staticmethod
    def _fmt_dist(m: float) -> str:
        if m < 1000:
            return f'{m:.0f} m'
        return f'{m / 1000:.3f} km'


class PhotoToolMixin:
    """Annotations photo : croix + miniature, indicateur de direction (œil)."""

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
            markersize=self._photo_cross_size, markeredgewidth=2.5, zorder=12)
        cross.pickradius = 12   # zone de clic élargie pour la croix
        artists.append(cross)
        try:
            img_arr  = np.array(PilImage.open(thumb_path).convert('RGB'))
            imgbox   = OffsetImage(img_arr, zoom=self._photo_zoom)
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

    def reload_photo_annotations(self):
        """Supprime les artistes photo existants puis redessine depuis _photo_data."""
        for artists in self._photo_artists:
            for art in artists:
                try:
                    art.remove()
                except Exception:
                    pass
        self._redraw_photos()
        self._redraw_notes()
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


class NoteToolMixin:
    """Annotations note : pastille + titre."""

    # ── Notes ────────────────────────────────────────────────────────

    def set_note_mode(self, active: bool):
        self._note_mode = active
        if active:
            self.setCursor(Qt.CrossCursor)
        elif not self._measure_mode and not self._photo_mode:
            self.setCursor(Qt.OpenHandCursor)

    def load_note_data(self, entries: list):
        self._note_data    = entries
        self._note_artists = []

    def add_note_annotation(self, x_m: float, y_m: float,
                             lat: float, lon: float,
                             titre: str, description: str):
        entry = {'x_m': x_m, 'y_m': y_m, 'lat': lat, 'lon': lon,
                 'titre': titre, 'description': description}
        self._note_data.append(entry)
        artists = self._draw_note_annotation(x_m, y_m, titre)
        self._note_artists.append(artists)
        self.draw_idle()

    def _draw_note_annotation(self, x_m: float, y_m: float, titre: str) -> list:
        dot, = self.ax.plot(
            x_m, y_m, 'o', color='#f39c12',
            markersize=14, markeredgecolor='#c07d10',
            markeredgewidth=1.5, zorder=14)
        dot.pickradius = 14
        # Icône stylo au centre
        icon, = self.ax.plot(
            x_m, y_m, marker=r'$\clubsuit$', color='white',
            markersize=7, zorder=15, linestyle='none')
        short = (titre[:22] + '…') if len(titre) > 22 else titre
        lbl = self.ax.annotate(
            short or '(sans titre)',
            xy=(x_m, y_m), xytext=(0, 16),
            textcoords='offset points',
            ha='center', va='bottom', fontsize=8, color='#333',
            zorder=16,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#fffde7',
                      edgecolor='#f39c12', alpha=0.92))
        return [dot, icon, lbl]

    def _redraw_notes(self):
        self._note_artists = []
        for entry in self._note_data:
            artists = self._draw_note_annotation(
                entry['x_m'], entry['y_m'], entry['titre'])
            self._note_artists.append(artists)

    def delete_note(self, index: int):
        if index < len(self._note_artists):
            for art in self._note_artists[index]:
                try:
                    art.remove()
                except Exception:
                    pass
            self._note_artists.pop(index)
        if index < len(self._note_data):
            self._note_data.pop(index)
        self.draw_idle()

    def update_note(self, index: int, titre: str, description: str):
        if index < len(self._note_data):
            self._note_data[index]['titre'] = titre
            self._note_data[index]['description'] = description
        # Redessine uniquement cette note
        if index < len(self._note_artists):
            for art in self._note_artists[index]:
                try:
                    art.remove()
                except Exception:
                    pass
            entry = self._note_data[index]
            artists = self._draw_note_annotation(
                entry['x_m'], entry['y_m'], titre)
            self._note_artists[index] = artists
        self.draw_idle()

    def _find_note_at(self, event, radius_px: int = 18) -> 'int | None':
        if not self._note_data or event.x is None or event.y is None:
            return None
        for i, entry in enumerate(self._note_data):
            try:
                dp = self.ax.transData.transform((entry['x_m'], entry['y_m']))
                if math.hypot(event.x - dp[0], event.y - dp[1]) <= radius_px:
                    return i
            except Exception:
                pass
        return None
