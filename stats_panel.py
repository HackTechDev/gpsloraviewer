"""
stats_panel.py — StatsPanel (panneau de statistiques GPS)
"""

from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from gps_nmea import GPSData


# ══════════════════════════════════════════════════════════════════════
#  Panneau de statistiques
# ══════════════════════════════════════════════════════════════════════

class StatsPanel(QFrame):
    _FIELDS = [
        ('Fichier',      None),
        ('Points GPS',   None),
        ('Distance',     None),
        ('Durée',        None),
        ('Altitude min', None),
        ('Altitude max', None),
        ('Alt. moyenne', None),
        ('Vitesse max',  None),
        ('Vitesse moy.', None),
    ]

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(210)
        self.setStyleSheet(
            'StatsPanel { background:#fafafa; border-left:1px solid #ddd; }')

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 10)
        root.setSpacing(0)

        # ── Titre bloc statistiques ──
        lbl_title = QLabel('STATISTIQUES')
        lbl_title.setFont(QFont('Arial', 8, QFont.Bold))
        lbl_title.setStyleSheet('color:#777; letter-spacing:1.2px;')
        root.addWidget(lbl_title)
        root.addSpacing(6)

        self._vals: dict[str, QLabel] = {}
        for key, _ in self._FIELDS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            lk = QLabel(key)
            lk.setFont(QFont('Arial', 9))
            lk.setStyleSheet('color:#999;')
            lk.setFixedWidth(90)
            lk.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            lv = QLabel('—')
            lv.setFont(QFont('Arial', 9, QFont.Bold))
            lv.setStyleSheet('color:#222;')
            lv.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lv.setWordWrap(True)

            row.addWidget(lk)
            row.addSpacing(6)
            row.addWidget(lv, 1)
            root.addLayout(row)
            self._vals[key] = lv

        # ── Séparateur ──
        root.addSpacing(10)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('background:#e0e0e0; max-height:1px;')
        root.addWidget(sep)
        root.addSpacing(8)

        # ── Titre bloc curseur ──
        lbl_cur = QLabel('CURSEUR')
        lbl_cur.setFont(QFont('Arial', 8, QFont.Bold))
        lbl_cur.setStyleSheet('color:#777; letter-spacing:1.2px;')
        root.addWidget(lbl_cur)
        root.addSpacing(6)

        self._hover = QLabel('—\n\n\n\n\n')
        self._hover.setFont(QFont('Courier', 9))
        self._hover.setStyleSheet('color:#333; line-height:160%;')
        self._hover.setWordWrap(True)
        self._hover.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(self._hover)

        root.addStretch()

        # ── Crédits ──
        credits = QLabel('© OpenStreetMap contributors')
        credits.setFont(QFont('Arial', 7))
        credits.setStyleSheet('color:#bbb;')
        credits.setAlignment(Qt.AlignCenter)
        root.addWidget(credits)

    def clear(self):
        for lv in self._vals.values():
            lv.setText('—')
        self._hover.setText('—')

    def refresh(self, gps: GPSData):
        dur = '—'
        if gps.duration_s is not None:
            h  = int(gps.duration_s // 3600)
            mn = int((gps.duration_s % 3600) // 60)
            s  = int(gps.duration_s % 60)
            dur = (f"{h}h {mn:02d}min {s:02d}s" if h
                   else f"{mn}min {s:02d}s")

        self._set('Fichier',      gps.filename)
        self._set('Points GPS',   f"{gps.count:,}")
        self._set('Distance',     f"{gps.total_dist:.1f} m")
        self._set('Durée',        dur)
        self._set('Altitude min', f"{gps.alt_min:.1f} m"  if gps.alt_min is not None else '—')
        self._set('Altitude max', f"{gps.alt_max:.1f} m"  if gps.alt_max is not None else '—')
        self._set('Alt. moyenne', f"{gps.alt_avg:.1f} m"  if gps.alt_avg is not None else '—')
        self._set('Vitesse max',  f"{gps.spd_max:.1f} km/h")
        self._set('Vitesse moy.', f"{gps.spd_avg:.1f} km/h")
        self._hover.setText('—')

    def update_cursor(self, gps: GPSData, index: int | None):
        if index is None or index >= gps.count:
            self._hover.setText('—')
            return
        p   = gps.points[index]
        spd = gps.speeds[index]
        alt = p['alt']
        lines = [
            f"Heure : {p['time']}",
            f"Lat   : {p['lat']:.5f}°",
            f"Lon   : {p['lon']:.5f}°",
            f"Alt   : {f'{alt:.1f} m' if alt is not None else '—'}",
            f"Vit   : {f'{spd:.1f} km/h' if spd is not None else '—'}",
            f"Dist  : {gps.distances[index]:.0f} m",
            f"Sats  : {p['sats']}",
        ]
        self._hover.setText('\n'.join(lines))

    def _set(self, key: str, val: str):
        if key in self._vals:
            self._vals[key].setText(val)
