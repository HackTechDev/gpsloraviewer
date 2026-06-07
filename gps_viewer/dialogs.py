"""
dialogs.py — CoordDialog, PhotoViewDialog, ParcoursPropDialog, SettingsDialog
"""

from pathlib import Path
from PIL import Image as PilImage

import numpy as np

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QSpinBox, QLineEdit,
    QGridLayout, QScrollArea, QPushButton, QTextEdit, QFormLayout,
    QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QSizePolicy,
    QGroupBox, QCheckBox, QSlider,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QApplication


def _read_exif(image_path: str) -> dict:
    """Lit date, appareil et focale depuis les métadonnées EXIF. Retourne {} si absent."""
    try:
        from PIL import ExifTags
        img = PilImage.open(image_path)
        raw = img._getexif()
        if not raw:
            return {}
        tags = {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}
        result = {}
        for key in ('DateTimeOriginal', 'DateTime'):
            if key in tags:
                result['date'] = str(tags[key])
                break
        if 'Model' in tags:
            result['model'] = str(tags['Model']).strip()
        if 'FocalLength' in tags:
            fl = tags['FocalLength']
            try:
                result['focal'] = f'{float(fl.numerator) / float(fl.denominator):.0f} mm'
            except Exception:
                result['focal'] = f'{fl} mm'
        return result
    except Exception:
        return {}


def _pil_to_pixmap(pil_img) -> QPixmap:
    """Convertit une image PIL RGB en QPixmap."""
    arr = np.ascontiguousarray(pil_img)
    h, w, c = arr.shape
    qimg = QImage(arr.data, w, h, w * c, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


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
#  Visionneuse photo plein format
# ══════════════════════════════════════════════════════════════════════

class PhotoViewDialog(QDialog):
    """Affiche la photo originale en plein format avec infos EXIF et rotation."""

    def __init__(self, image_path: str, lat: float, lon: float,
                 titre: str = '', description: str = '',
                 thumb_path: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle(Path(image_path).name)
        self.deletion_requested = False
        self._image_path  = image_path
        self._thumb_path  = thumb_path
        self._orig_pil    = None
        self._rotation_deg = 0          # degrés CW cumulés
        self._img_label   = None
        screen = QApplication.primaryScreen().availableGeometry()
        self._max_w = int(screen.width()  * 0.9)
        self._max_h = int(screen.height() * 0.85)
        try:
            self._orig_pil = PilImage.open(image_path).convert('RGB')
        except Exception:
            pass
        self._build(image_path, lat, lon, titre, description)

    @property
    def rotation_applied(self) -> bool:
        return self._rotation_deg % 360 != 0

    def _update_image(self):
        """Rafraîchit le QLabel avec l'image pivotée courante."""
        if self._orig_pil is None or self._img_label is None:
            return
        img = self._orig_pil.rotate(-self._rotation_deg, expand=True)
        pixmap = _pil_to_pixmap(img)
        scaled = pixmap.scaled(self._max_w, self._max_h,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._img_label.setPixmap(scaled)
        self._img_label.adjustSize()

    def _rotate_left(self):
        self._rotation_deg = (self._rotation_deg - 90) % 360
        self._update_image()

    def _rotate_right(self):
        self._rotation_deg = (self._rotation_deg + 90) % 360
        self._update_image()

    def accept(self):
        if self._orig_pil and self.rotation_applied and not self.deletion_requested:
            try:
                rotated = self._orig_pil.rotate(-self._rotation_deg, expand=True)
                ext = Path(self._image_path).suffix.lower()
                if ext in ('.jpg', '.jpeg'):
                    rotated.save(self._image_path, 'JPEG', quality=95)
                else:
                    rotated.save(self._image_path)
                if self._thumb_path and Path(self._thumb_path).exists():
                    thumb = rotated.copy()
                    thumb.thumbnail((80, 80), PilImage.LANCZOS)
                    thumb.save(self._thumb_path, 'JPEG', quality=85)
            except Exception as e:
                QMessageBox.warning(self, 'Erreur rotation',
                                    f'Impossible de sauvegarder la rotation :\n{e}')
        super().accept()

    def _build(self, image_path: str, lat: float, lon: float,
               titre: str, description: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── Image ─────────────────────────────────────────────────────
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignCenter)

        if self._orig_pil:
            self._update_image()
            pw = self._img_label.pixmap().width()
            ph = self._img_label.pixmap().height()
            if pw > 1200 or ph > 900:
                scroll = QScrollArea()
                scroll.setWidget(self._img_label)
                scroll.setWidgetResizable(False)
                scroll.setAlignment(Qt.AlignCenter)
                layout.addWidget(scroll)
            else:
                layout.addWidget(self._img_label)
        else:
            self._img_label.setText(f"Impossible de charger l'image :\n{image_path}")
            layout.addWidget(self._img_label)

        # ── EXIF ──────────────────────────────────────────────────────
        exif = _read_exif(image_path)
        if exif:
            parts = []
            if 'date' in exif:
                parts.append(exif['date'])
            if 'model' in exif:
                parts.append(exif['model'])
            if 'focal' in exif:
                parts.append(exif['focal'])
            if parts:
                lbl_exif = QLabel('  |  '.join(parts))
                lbl_exif.setStyleSheet('color:#888; font-size:10px;')
                layout.addWidget(lbl_exif)

        # ── Coordonnées + chemin ──────────────────────────────────────
        info = QLabel(
            f'<span style="color:#555;">'
            f'{lat:.6f}° N &nbsp; {lon:.6f}° E'
            f'</span>'
            f'<br><span style="color:#aaa; font-size:10px;">{image_path}</span>')
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        # ── Rotation ──────────────────────────────────────────────────
        if self._orig_pil:
            rot_row = QHBoxLayout()
            rot_row.addWidget(QLabel('Rotation :'))
            btn_ccw = QPushButton('↶')
            btn_ccw.setFixedWidth(40)
            btn_ccw.setToolTip('Rotation 90° vers la gauche')
            btn_ccw.clicked.connect(self._rotate_left)
            rot_row.addWidget(btn_ccw)
            btn_cw = QPushButton('↷')
            btn_cw.setFixedWidth(40)
            btn_cw.setToolTip('Rotation 90° vers la droite')
            btn_cw.clicked.connect(self._rotate_right)
            rot_row.addWidget(btn_cw)
            rot_row.addStretch()
            layout.addLayout(rot_row)

        # ── Titre et description ──────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 4, 0, 4)

        self._titre_edit = QLineEdit(titre)
        self._titre_edit.setPlaceholderText('Titre de la photo…')
        form.addRow('Titre :', self._titre_edit)

        self._desc_edit = QTextEdit()
        self._desc_edit.setPlainText(description)
        self._desc_edit.setPlaceholderText('Description…')
        line_h = self._desc_edit.fontMetrics().lineSpacing()
        self._desc_edit.setFixedHeight(line_h * 5 + 14)
        form.addRow('Description :', self._desc_edit)

        layout.addLayout(form)

        # ── Barre de boutons ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_del = QPushButton('🗑  Supprimer')
        btn_del.setFixedWidth(130)
        btn_del.setStyleSheet(
            'QPushButton { color:white; background:#e74c3c; border-radius:4px; padding:4px 8px; }'
            'QPushButton:hover { background:#c0392b; }')
        btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(btn_del)

        btn_row.addSpacing(10)

        btn_close = QPushButton('Fermer')
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)
        self.adjustSize()

    def _on_delete(self):
        reply = QMessageBox.question(
            self, 'Supprimer la photo',
            'Supprimer définitivement cette photo et sa miniature\n'
            'ainsi que sa référence sur la carte ?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.deletion_requested = True
            self.accept()


# ══════════════════════════════════════════════════════════════════════
#  Dialog propriétés du parcours
# ══════════════════════════════════════════════════════════════════════

class ParcoursPropDialog(QDialog):
    def __init__(self, titre: str = '', description: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Propriétés du parcours')
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._titre_edit = QLineEdit(titre)
        self._titre_edit.setPlaceholderText('Nom du parcours…')
        form.addRow('Titre :', self._titre_edit)

        self._desc_edit = QTextEdit()
        self._desc_edit.setPlainText(description)
        self._desc_edit.setPlaceholderText('Description du parcours…')
        self._desc_edit.setFixedHeight(120)
        form.addRow('Description :', self._desc_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText('Enregistrer')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


# ══════════════════════════════════════════════════════════════════════
#  Dialogue Préférences / Paramétrage
# ══════════════════════════════════════════════════════════════════════

class SettingsDialog(QDialog):
    """Dialogue de préférences avec application immédiate des valeurs."""

    def __init__(self, parent=None, *,
                 track_linewidth: float = 2.5,
                 map_alpha: float       = 1.0,
                 photo_zoom: float      = 0.8,
                 photo_cross: int       = 16,
                 cursor_dot: int        = 12,
                 autopan_margin: int    = 0,
                 remember_layout: bool  = False,
                 on_changed=None):
        super().__init__(parent)
        self.setWindowTitle('Préférences')
        self.setMinimumWidth(360)
        self._on_changed = on_changed  # callable(key, value) appelé à chaque modification

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Groupe Carte ─────────────────────────────────────────────
        grp_map = QGroupBox('Carte')
        form_map = QFormLayout(grp_map)
        form_map.setSpacing(8)

        self._sb_linewidth = QDoubleSpinBox()
        self._sb_linewidth.setRange(0.5, 10.0)
        self._sb_linewidth.setSingleStep(0.5)
        self._sb_linewidth.setSuffix(' px')
        self._sb_linewidth.setValue(track_linewidth)
        self._sb_linewidth.valueChanged.connect(
            lambda v: self._emit('track_linewidth', v))
        form_map.addRow('Épaisseur de la trace :', self._sb_linewidth)

        self._sl_alpha = QSlider(Qt.Horizontal)
        self._sl_alpha.setRange(0, 100)
        self._sl_alpha.setValue(int(map_alpha * 100))
        self._lbl_alpha = QLabel(f'{int(map_alpha * 100)} %')
        self._lbl_alpha.setFixedWidth(38)
        self._sl_alpha.valueChanged.connect(self._on_alpha_changed)
        row_alpha = QHBoxLayout()
        row_alpha.addWidget(self._sl_alpha, 1)
        row_alpha.addWidget(self._lbl_alpha)
        form_map.addRow('Opacité fond de carte :', row_alpha)

        self._sb_photo_zoom = QDoubleSpinBox()
        self._sb_photo_zoom.setRange(0.2, 3.0)
        self._sb_photo_zoom.setSingleStep(0.1)
        self._sb_photo_zoom.setValue(photo_zoom)
        self._sb_photo_zoom.valueChanged.connect(
            lambda v: self._emit('photo_zoom', v))
        form_map.addRow('Taille icônes photo :', self._sb_photo_zoom)

        self._sb_photo_cross = QSpinBox()
        self._sb_photo_cross.setRange(4, 64)
        self._sb_photo_cross.setSuffix(' px')
        self._sb_photo_cross.setValue(photo_cross)
        self._sb_photo_cross.valueChanged.connect(
            lambda v: self._emit('photo_cross', v))
        form_map.addRow('Taille croix photo :', self._sb_photo_cross)

        self._sb_cursor = QSpinBox()
        self._sb_cursor.setRange(4, 40)
        self._sb_cursor.setSuffix(' px')
        self._sb_cursor.setValue(cursor_dot)
        self._sb_cursor.valueChanged.connect(
            lambda v: self._emit('cursor_dot', v))
        form_map.addRow('Taille curseur rouge :', self._sb_cursor)

        self._sb_autopan = QSpinBox()
        self._sb_autopan.setRange(0, 400)
        self._sb_autopan.setSuffix(' px')
        self._sb_autopan.setToolTip('0 = pan dès que le curseur sort de la vue')
        self._sb_autopan.setValue(autopan_margin)
        self._sb_autopan.valueChanged.connect(
            lambda v: self._emit('autopan_margin', v))
        form_map.addRow('Marge auto-pan :', self._sb_autopan)

        layout.addWidget(grp_map)

        # ── Groupe Général ───────────────────────────────────────────
        grp_gen = QGroupBox('Général')
        form_gen = QFormLayout(grp_gen)
        form_gen.setSpacing(8)

        self._chk_layout = QCheckBox('Mémoriser la mise en page')
        self._chk_layout.setChecked(remember_layout)
        self._chk_layout.toggled.connect(
            lambda v: self._emit('remember_layout', v))
        form_gen.addRow(self._chk_layout)

        layout.addWidget(grp_gen)

        # ── Boutons ──────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── Accesseurs ──────────────────────────────────────────────────

    @property
    def track_linewidth(self) -> float:
        return self._sb_linewidth.value()

    @property
    def map_alpha(self) -> float:
        return self._sl_alpha.value() / 100.0

    @property
    def photo_zoom(self) -> float:
        return self._sb_photo_zoom.value()

    @property
    def photo_cross(self) -> int:
        return self._sb_photo_cross.value()

    @property
    def cursor_dot(self) -> int:
        return self._sb_cursor.value()

    @property
    def autopan_margin(self) -> int:
        return self._sb_autopan.value()

    @property
    def remember_layout(self) -> bool:
        return self._chk_layout.isChecked()

    # ── Interne ─────────────────────────────────────────────────────

    def _on_alpha_changed(self, val: int):
        self._lbl_alpha.setText(f'{val} %')
        self._emit('map_alpha', val / 100.0)

    def _emit(self, key: str, value):
        if callable(self._on_changed):
            self._on_changed(key, value)
