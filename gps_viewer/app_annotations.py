"""
app_annotations.py — AnnotationsMixin : gestion des annotations photo et
                     note côté fenêtre principale (dialogues d'ajout,
                     d'édition et de suppression, copie des photos).
                     Le dessin sur la carte est dans map_tools.py.
                     Extrait de gps_viewer.py (MainWindow en hérite) pour
                     garder ce dernier plus lisible.
"""

import datetime
import os
import shutil
from pathlib import Path

from PIL import Image as PilImage
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from gps_nmea import _webmerc_to_latlon
from dialogs import PhotoViewDialog, NoteDialog
from app_config import _TRACKS_IMG_DIR


class AnnotationsMixin:
    """Annotations photo / note de MainWindow.

    Mixin pour MainWindow — s'appuie sur _map, _sb, _act_photo, _act_note
    et _save_track_json définis dans gps_viewer.MainWindow.
    """

    # ── Annotations photo ─────────────────────────────────────────────

    def _on_photo_clicked(self, index: int):
        """Ouvre la photo en plein format ; sauvegarde titre/description ; supprime si demandé."""
        if index >= len(self._map._photo_data):
            return
        entry = self._map._photo_data[index]
        orig  = entry['orig_path']
        if not Path(orig).exists():
            QMessageBox.warning(self, 'Fichier introuvable',
                                f'La photo originale est introuvable :\n{orig}')
            return
        dlg = PhotoViewDialog(
            orig, entry['lat'], entry['lon'],
            entry.get('titre', ''), entry.get('description', ''),
            thumb_path=entry.get('thumb_path', ''), parent=self)
        dlg.exec_()
        if dlg.deletion_requested:
            self._delete_photo(index)
        else:
            new_titre = dlg._titre_edit.text().strip()
            new_desc  = dlg._desc_edit.toPlainText().strip()
            title_changed = (new_titre != entry.get('titre', '')
                             or new_desc != entry.get('description', ''))
            if title_changed:
                self._map._photo_data[index]['titre']       = new_titre
                self._map._photo_data[index]['description'] = new_desc
                self._save_track_json()
            if dlg.rotation_applied:
                self._map.reload_photo_annotations()
                self._sb.showMessage('Photo pivotée et miniature mise à jour.')
            elif title_changed:
                self._sb.showMessage('Annotations photo mises à jour.')

    def _delete_photo(self, index: int):
        """Supprime fichiers, artistes carte et entrée JSON pour l'annotation index."""
        if index >= len(self._map._photo_data):
            return
        entry = self._map._photo_data[index]

        # Suppression des fichiers
        for key in ('orig_path', 'thumb_path'):
            p = Path(entry.get(key, ''))
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        # Retrait des artistes de la carte
        if index < len(self._map._photo_artists):
            for art in self._map._photo_artists[index]:
                try:
                    art.remove()
                except Exception:
                    pass
            self._map._photo_artists.pop(index)

        self._map._photo_data.pop(index)
        self._map.draw_idle()

        # Mise à jour du JSON
        self._save_track_json()
        self._sb.showMessage(
            f'Photo supprimée : {Path(entry["orig_path"]).name}')

    def _on_photo_requested(self, x_m: float, y_m: float):
        """Clic en mode photo : ouvre le sélecteur, copie et affiche la photo."""
        lat, lon = _webmerc_to_latlon(x_m, y_m)
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choisir une photo', os.getcwd(),
            'Images (*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp)'
            ';;Tous les fichiers (*)')
        if not path:
            return
        try:
            orig_path, thumb_path = self._save_photo(path)
        except Exception as exc:
            QMessageBox.critical(self, 'Erreur photo',
                                 f'Impossible de traiter la photo :\n{exc}')
            return
        self._map.add_photo_annotation(
            x_m, y_m, lat, lon, str(orig_path), str(thumb_path))
        self._save_track_json()
        self._sb.showMessage(
            f'Photo ajoutée : {Path(orig_path).name}'
            f'  •  {lat:.6f}° N  {lon:.6f}° E')

    # ── Mode photo : exclusivité avec note ──────────────────────────

    def _on_photo_mode_toggled(self, active: bool):
        if active and self._act_note.isChecked():
            self._act_note.blockSignals(True)
            self._act_note.setChecked(False)
            self._act_note.blockSignals(False)
            self._map.set_note_mode(False)
        self._map.set_photo_mode(active)

    # ── Annotations note ─────────────────────────────────────────────

    def _on_note_mode_toggled(self, active: bool):
        if active and self._act_photo.isChecked():
            self._act_photo.blockSignals(True)
            self._act_photo.setChecked(False)
            self._act_photo.blockSignals(False)
            self._map.set_photo_mode(False)
        self._map.set_note_mode(active)

    def _on_note_requested(self, x_m: float, y_m: float):
        lat, lon = _webmerc_to_latlon(x_m, y_m)
        dlg = NoteDialog(self)
        if dlg.exec_() != 1:   # QDialog.Accepted == 1
            return
        if not dlg.titre and not dlg.description:
            return
        self._map.add_note_annotation(
            x_m, y_m, lat, lon, dlg.titre, dlg.description)
        self._save_track_json()
        self._sb.showMessage(
            f'Note ajoutée : {dlg.titre or "(sans titre)"}  •  '
            f'{lat:.6f}° N  {lon:.6f}° E')

    def _on_note_clicked(self, index: int):
        if index >= len(self._map._note_data):
            return
        entry = self._map._note_data[index]
        dlg = NoteDialog(
            self,
            titre       = entry.get('titre', ''),
            description = entry.get('description', ''),
            edit_mode   = True)
        if dlg.exec_() != 1:
            return
        if dlg.deleted:
            self._map.delete_note(index)
            self._save_track_json()
            self._sb.showMessage('Note supprimée.')
        else:
            self._map.update_note(index, dlg.titre, dlg.description)
            self._save_track_json()
            self._sb.showMessage('Note mise à jour.')

    def _save_photo(self, src_path: str):
        """Copie l'original et crée la miniature dans tracks/images/."""
        _TRACKS_IMG_DIR.mkdir(parents=True, exist_ok=True)
        ts  = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        ext = Path(src_path).suffix.lower() or '.jpg'
        i   = 1
        while (_TRACKS_IMG_DIR / f'photo_{ts}_{i:03d}{ext}').exists():
            i += 1
        orig_dest  = _TRACKS_IMG_DIR / f'photo_{ts}_{i:03d}{ext}'
        thumb_dest = _TRACKS_IMG_DIR / f'photo_{ts}_{i:03d}_thumb.jpg'
        shutil.copy2(src_path, orig_dest)
        img = PilImage.open(src_path).convert('RGB')
        img.thumbnail((80, 80), PilImage.LANCZOS)
        img.save(thumb_dest, 'JPEG', quality=85)
        return orig_dest, thumb_dest
