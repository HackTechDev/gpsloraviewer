"""
app_config.py — Chemins de configuration/données de l'application et
              PersistenceMixin : chargement/sauvegarde des préférences, de
              la mise en page et de la liste des fichiers récents.
              Extrait de gps_viewer.py (MainWindow en hérite) pour garder
              ce dernier plus lisible.
"""

import json
import os
from pathlib import Path

from PyQt5.QtWidgets import QAction

# ── Constantes de configuration ─────────────────────────────────────────
_CONFIG_DIR       = Path.home() / '.config' / 'gps_viewer'
_RECENT_FILE      = _CONFIG_DIR / 'recent_tracks.json'
_LAST_TRACK_FILE  = _CONFIG_DIR / 'last_track.txt'
_SETTINGS_FILE    = _CONFIG_DIR / 'settings.json'
_LAYOUT_FILE      = _CONFIG_DIR / 'layout.json'
_MAX_RECENT       = 10

_TRACKS_DIR     = Path(__file__).parent / 'tracks'
_TRACKS_IMG_DIR = _TRACKS_DIR / 'images'
_TRACKS_JSON    = _TRACKS_DIR / 'track.json'


class PersistenceMixin:
    """Persistance disque : préférences, mise en page, fichiers récents.

    Mixin pour MainWindow — les méthodes ci-dessous s'appuient sur des
    attributs et widgets définis dans gps_viewer.MainWindow (préférences
    _pref_*, splitters _charts_split/_vsplit, menu _recent_menu…).
    """

    # ── Préférences ──────────────────────────────────────────────────

    def _load_settings(self):
        try:
            if _SETTINGS_FILE.exists():
                d = json.loads(_SETTINGS_FILE.read_text(encoding='utf-8'))
                self._pref_track_linewidth = float(d.get('track_linewidth', self._pref_track_linewidth))
                self._pref_map_alpha       = float(d.get('map_alpha',       self._pref_map_alpha))
                self._pref_photo_zoom      = float(d.get('photo_zoom',      self._pref_photo_zoom))
                self._pref_photo_cross     = int(d.get('photo_cross',       self._pref_photo_cross))
                self._pref_cursor_dot      = int(d.get('cursor_dot',        self._pref_cursor_dot))
                self._pref_autopan_margin  = int(d.get('autopan_margin',    self._pref_autopan_margin))
                self._pref_remember_layout = bool(d.get('remember_layout',  self._pref_remember_layout))
        except Exception:
            pass

    def _save_settings(self):
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        d = {
            'track_linewidth': self._pref_track_linewidth,
            'map_alpha':       self._pref_map_alpha,
            'photo_zoom':      self._pref_photo_zoom,
            'photo_cross':     self._pref_photo_cross,
            'cursor_dot':      self._pref_cursor_dot,
            'autopan_margin':  self._pref_autopan_margin,
            'remember_layout': self._pref_remember_layout,
        }
        _SETTINGS_FILE.write_text(json.dumps(d, indent=2), encoding='utf-8')

    # ── Mise en page ─────────────────────────────────────────────────

    def _save_layout(self):
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            d = {
                'width':        self.width(),
                'height':       self.height(),
                'splitter_charts': self._charts_split.sizes(),
                'splitter_v':      self._vsplit.sizes(),
            }
            _LAYOUT_FILE.write_text(json.dumps(d), encoding='utf-8')
        except Exception:
            pass

    def _restore_layout(self):
        try:
            if _LAYOUT_FILE.exists():
                d = json.loads(_LAYOUT_FILE.read_text(encoding='utf-8'))
                self.resize(d.get('width', self.width()), d.get('height', self.height()))
                if 'splitter_charts' in d:
                    self._charts_split.setSizes(d['splitter_charts'])
                if 'splitter_v' in d:
                    self._vsplit.setSizes(d['splitter_v'])
        except Exception:
            pass

    # ── Fichiers récents ─────────────────────────────────────────────

    def _load_recent(self) -> list:
        try:
            if _RECENT_FILE.exists():
                return json.loads(_RECENT_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
        return []

    def _save_recent(self, files: list):
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _RECENT_FILE.write_text(
                json.dumps(files, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _add_to_recent(self, filepath: str):
        files = self._load_recent()
        filepath = os.path.abspath(filepath)
        if filepath in files:
            files.remove(filepath)
        files.insert(0, filepath)
        files = [f for f in files if os.path.exists(f)][:_MAX_RECENT]
        self._save_recent(files)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        files = self._load_recent()
        if not files:
            a = QAction('(aucun)', self)
            a.setEnabled(False)
            self._recent_menu.addAction(a)
            return
        for fp in files:
            label = os.path.basename(fp)
            a = QAction(label, self)
            a.setToolTip(fp)
            a.triggered.connect(lambda checked=False, p=fp: self._apply_track_json(Path(p)))
            self._recent_menu.addAction(a)
        self._recent_menu.addSeparator()
        clear_a = QAction('Effacer la liste', self)
        clear_a.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear_a)

    def _clear_recent(self):
        self._save_recent([])
        self._refresh_recent_menu()

    # ── Dernier parcours ouvert ──────────────────────────────────────

    def _resolve_startup_track(self) -> Path:
        """Retourne le dernier fichier JSON utilisé, ou le chemin par défaut."""
        try:
            if _LAST_TRACK_FILE.exists():
                p = Path(_LAST_TRACK_FILE.read_text(encoding='utf-8').strip())
                if p.exists():
                    return p
        except Exception:
            pass
        return _TRACKS_JSON

    def _persist_track_path(self):
        """Sauvegarde le chemin du fichier de trace actif pour le prochain démarrage."""
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _LAST_TRACK_FILE.write_text(
                str(self._current_track_path), encoding='utf-8')
        except Exception:
            pass
