"""
dialogs.py — CoordDialog, PhotoViewDialog, ParcoursPropDialog
"""

from pathlib import Path
from PIL import Image as PilImage

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QDoubleSpinBox, QSpinBox, QLineEdit,
    QGridLayout, QScrollArea, QPushButton, QTextEdit, QFormLayout,
    QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication


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
    """Affiche la photo originale en plein format dans une fenêtre dédiée."""

    def __init__(self, image_path: str, lat: float, lon: float,
                 titre: str = '', description: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle(Path(image_path).name)
        self.deletion_requested = False
        self._build(image_path, lat, lon, titre, description)

    def _build(self, image_path: str, lat: float, lon: float,
               titre: str, description: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            layout.addWidget(QLabel(f'Impossible de charger l\'image :\n{image_path}'))
        else:
            # Taille max = 90 % de l'écran disponible
            screen = QApplication.primaryScreen().availableGeometry()
            max_w  = int(screen.width()  * 0.9)
            max_h  = int(screen.height() * 0.85)
            scaled = pixmap.scaled(max_w, max_h,
                                   Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
            lbl_img = QLabel()
            lbl_img.setPixmap(scaled)
            lbl_img.setAlignment(Qt.AlignCenter)

            if scaled.width() > 1200 or scaled.height() > 900:
                scroll = QScrollArea()
                scroll.setWidget(lbl_img)
                scroll.setWidgetResizable(False)
                scroll.setAlignment(Qt.AlignCenter)
                layout.addWidget(scroll)
            else:
                layout.addWidget(lbl_img)

        # Coordonnées + chemin
        info = QLabel(
            f'<span style="color:#555;">'
            f'{lat:.6f}° N &nbsp; {lon:.6f}° E'
            f'</span>'
            f'<br><span style="color:#aaa; font-size:10px;">{image_path}</span>')
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

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

        # ── Barre de boutons ─────────────────────────────────────────
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
