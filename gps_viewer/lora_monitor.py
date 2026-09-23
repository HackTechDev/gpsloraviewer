"""
lora_monitor.py — LoraMonitorWindow : petite fenêtre flottante affichant en
                  direct les données GPS reçues par le récepteur LoRa
                  (dernière position décodée, état du fix, signal radio,
                  compteurs et trames brutes).

Utile même sans fix GPS : l'émetteur terrain relaie ses trames $GPRMC
(statut V) avant d'avoir capté les satellites, ce qui permet de vérifier
que la liaison radio fonctionne.
"""

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from gps_nmea import decode_nmea_fields
from lora_common import parse_rssi_line, rssi_quality

# L'émetteur terrain transmet une trame toutes les 10 s (gps_lora_logger.ino)
_PERIOD_S   = 10
_MAX_LINES  = 200
_C_OK, _C_WARN, _C_BAD, _C_IDLE = '#27ae60', '#e67e22', '#c0392b', '#7f8c8d'


class LoraMonitorWindow(QWidget):
    """Fenêtre outil non modale : la fermer n'arrête pas la réception."""

    _FIELDS = [
        ('time',   'Heure (UTC)'),
        ('date',   'Date'),
        ('lat',    'Latitude'),
        ('lon',    'Longitude'),
        ('alt',    'Altitude'),
        ('speed',  'Vitesse'),
        ('course', 'Cap'),
        ('sats',   'Satellites'),
        ('hdop',   'HDOP'),
    ]
    _POS_KEYS = ('lat', 'lon', 'speed', 'course')   # n'ont de sens qu'avec un fix

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool)
        self.setWindowTitle('Données GPS reçues')
        self.resize(420, 680)
        self._last_rx: float | None = None   # time.monotonic() dernière ligne
        self._active = False
        self._build()
        self._age_timer = QTimer(self, interval=1000)
        self._age_timer.timeout.connect(self._refresh_age)
        self.reset()

    # ── Construction ─────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # ── État de la réception ─────────────────────────────────────
        self._lbl_state = QLabel()
        self._lbl_state.setStyleSheet('font-weight:bold; font-size:13px;')
        self._lbl_age = QLabel()
        self._lbl_age.setStyleSheet('font-size:11px;')
        self._lbl_fix = QLabel()
        self._lbl_fix.setStyleSheet('font-size:12px;')
        self._lbl_fix.setWordWrap(True)
        for w in (self._lbl_state, self._lbl_age, self._lbl_fix):
            lay.addWidget(w)

        # ── Dernière position ────────────────────────────────────────
        box = QGroupBox('Dernière position décodée')
        form = QFormLayout(box)
        form.setVerticalSpacing(3)
        mono = QFont('monospace')
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(self.font().pointSizeF() * 0.95)
        self._vals = {}
        for key, label in self._FIELDS:
            v = QLabel()
            v.setFont(mono)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(f'{label} :', v)
            self._vals[key] = v
        lay.addWidget(box)

        # ── Radio + compteurs ────────────────────────────────────────
        box_rx = QGroupBox('Liaison radio')
        form_rx = QFormLayout(box_rx)
        form_rx.setVerticalSpacing(3)
        self._lbl_rssi = QLabel()
        self._lbl_counts = QLabel()
        self._lbl_counts.setWordWrap(True)
        form_rx.addRow('Signal :', self._lbl_rssi)
        form_rx.addRow('Trames :', self._lbl_counts)
        lay.addWidget(box_rx)

        # ── Trames brutes ────────────────────────────────────────────
        lay.addWidget(QLabel('Trames brutes reçues :'))
        self._raw = QPlainTextEdit()
        self._raw.setReadOnly(True)
        self._raw.setFont(mono)
        self._raw.setMaximumBlockCount(_MAX_LINES)
        self._raw.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._raw.setMinimumHeight(150)
        self._raw.setStyleSheet(
            'QPlainTextEdit { background:#131d2a; color:#cfe3f5; font-size:10px; }')
        lay.addWidget(self._raw, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_clear = QPushButton('Vider')
        btn_clear.setToolTip('Efface les trames brutes affichées')
        btn_clear.clicked.connect(self._raw.clear)
        btn_close = QPushButton('Fermer')
        btn_close.setToolTip('Ferme la fenêtre (la réception continue)')
        btn_close.clicked.connect(self.close)
        row.addWidget(btn_clear)
        row.addWidget(btn_close)
        lay.addLayout(row)

    # ── API appelée par MainWindow ───────────────────────────────────

    def reset(self):
        self._last_rx = None
        self._n_lines = self._n_nmea = self._n_bad = self._n_fix = 0
        self._rssi: tuple | None = None
        for v in self._vals.values():
            v.setText('—')
        self._raw.clear()
        self._lbl_fix.setText('')
        self._lbl_rssi.setText('—')
        self._refresh_counts()
        self._refresh_age()

    def reception_started(self, port: str, baud: int):
        self.reset()
        self._active = True
        self._port_desc = f'{port} @ {baud} baud'
        self._age_timer.start()
        self._refresh_age()

    def reception_stopped(self):
        self._active = False
        self._age_timer.stop()
        self._refresh_age()

    def on_line(self, line: str, valid: bool):
        """Ligne reçue du port série (trame NMEA ou diagnostic '#')."""
        self._last_rx = time.monotonic()
        self._n_lines += 1
        is_nmea = line.startswith('$')
        if is_nmea and not valid:
            self._n_bad += 1
            self._raw.appendPlainText(f'✕ {line}   (checksum invalide)')
        else:
            self._raw.appendPlainText(line)
        if is_nmea and valid:
            self._n_nmea += 1
            fields = decode_nmea_fields(line)
            if fields:
                self._show_fields(fields)
        rssi = parse_rssi_line(line)
        if rssi is not None:
            self._rssi = rssi
            self._show_rssi()
        self._refresh_counts()
        self._refresh_age()

    # ── Affichage ────────────────────────────────────────────────────

    def _show_fields(self, f: dict):
        if f.get('fix'):
            self._n_fix += 1
            self._lbl_fix.setText(f'<span style="color:{_C_OK}">●</span> '
                                  'Fix GPS valide')
        else:
            self._lbl_fix.setText(
                f'<span style="color:{_C_WARN}">●</span> Pas de fix GPS — '
                "l'émetteur attend les satellites (trames reçues sans position)")
        fmt = {
            'time':   lambda v: v,
            'date':   lambda v: v,
            'lat':    lambda v: f'{v:+.6f}°',
            'lon':    lambda v: f'{v:+.6f}°',
            'alt':    lambda v: f'{v:.1f} m',
            'speed':  lambda v: f'{v:.1f} km/h',
            'course': lambda v: f'{v:.0f}°',
            'sats':   lambda v: str(v),
            'hdop':   lambda v: f'{v:.1f}',
        }
        src = dict(f, speed=f.get('speed_kmh'))
        for key, conv in fmt.items():
            if key in self._POS_KEYS and not f.get('fix'):
                # sans fix : ne pas laisser une ancienne position passer pour actuelle
                self._vals[key].setText('—')
            elif src.get(key) is not None:
                self._vals[key].setText(conv(src[key]))
            # champ absent de cette trame (ex. altitude dans une RMC) :
            # on garde la dernière valeur connue

    def _show_rssi(self):
        pkt, rssi = self._rssi
        q = rssi_quality(rssi)
        color = {'bon': _C_OK, 'moyen': _C_WARN}.get(q, _C_BAD)
        self._lbl_rssi.setText(
            f'<b style="color:{color}">{rssi} dBm</b> ({q})  •  paquet n° {pkt}')

    def _refresh_counts(self):
        self._lbl_counts.setText(
            f'{self._n_nmea} NMEA valide{"s" if self._n_nmea > 1 else ""}  •  '
            f'{self._n_fix} avec fix  •  '
            f'{self._n_bad} rejetée{"s" if self._n_bad > 1 else ""} (checksum)  •  '
            f'{self._n_lines} ligne{"s" if self._n_lines > 1 else ""} au total')

    def _refresh_age(self):
        if not self._active:
            self._lbl_state.setText(f'<span style="color:{_C_IDLE}">●</span> '
                                    'Réception arrêtée')
            self._lbl_age.setText('Démarrez la réception avec le bouton « ◎ LoRa Live ».'
                                  if self._last_rx is None else '')
            return
        self._lbl_state.setText(f'<span style="color:{_C_OK}">●</span> '
                                f'Réception active — {self._port_desc}')
        if self._last_rx is None:
            self._lbl_age.setText(f'<span style="color:{_C_IDLE}">'
                                  'En attente de la première trame…</span>')
            return
        age = time.monotonic() - self._last_rx
        color = (_C_OK if age <= _PERIOD_S * 1.5
                 else _C_WARN if age <= _PERIOD_S * 3 else _C_BAD)
        self._lbl_age.setText(f'<span style="color:{color}">'
                              f'Dernière trame il y a {age:.0f} s</span>'
                              f'  (émission toutes les {_PERIOD_S} s)')
