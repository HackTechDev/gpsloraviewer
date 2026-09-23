"""
lora_thread.py — QThread de réception GPS série (LoRa / NMEA)
             Lit le port série, émet un signal par point GPGGA valide,
             et sauvegarde toutes les trames NMEA dans un fichier.
"""

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from gps_nmea import parse_gpgga, parse_gprmc, verify_checksum
from lora_common import (default_lora_output_path, BAUD_RATE_DEFAULT,  # noqa: F401 — réexporté
                         serial_error_hint)


class LoraThread(QThread):
    """Lit le port série en arrière-plan et émet les points GPS valides."""

    # Point GPGGA parsé : dict avec lat, lon, alt, time, sats, hdop
    point_received = pyqtSignal(dict)
    # Erreur fatale (port inaccessible, déconnexion…)
    error_occurred = pyqtSignal(str)
    # Chaque ligne non vide reçue (trame NMEA ou diagnostic '#'), et pour
    # les trames '$' la validité du checksum (True pour les autres lignes)
    line_received  = pyqtSignal(str, bool)

    def __init__(self, port: str, baud: int = BAUD_RATE_DEFAULT,
                 output_path: 'Path | None' = None):
        super().__init__()
        self._port        = port
        self._baud        = baud
        self._output_path = Path(output_path) if output_path else default_lora_output_path()
        self._running     = False

    @property
    def output_path(self) -> Path:
        return self._output_path

    def stop(self):
        """Demande l'arrêt propre de la boucle de lecture."""
        self._running = False

    def run(self):
        try:
            import serial
        except ImportError:
            self.error_occurred.emit(
                'pyserial non installé.\nExécutez : pip install pyserial')
            return

        self._running = True
        try:
            with serial.Serial(self._port, self._baud, timeout=1) as ser, \
                 open(self._output_path, 'w', encoding='utf-8') as f:

                while self._running:
                    raw = ser.readline()
                    if not raw:
                        continue

                    # utf-8 : les messages '#' du firmware contiennent des accents/tirets
                    line = raw.decode('utf-8', errors='replace').rstrip()
                    if not line:
                        continue
                    valid = not line.startswith('$') or verify_checksum(line)
                    self.line_received.emit(line, valid)

                    # Toutes les trames NMEA au checksum valide sont
                    # sauvegardées (rejette le bruit radio de la liaison LoRa)
                    if line.startswith('$') and valid:
                        f.write(line + '\r\n')
                        f.flush()

                    # Trames de position : GGA (avec alt/sats) ou RMC
                    if line.startswith(('$GPGGA', '$GNGGA')):
                        pt = parse_gpgga(line)
                        if pt:
                            self.point_received.emit(pt)
                    elif line.startswith(('$GPRMC', '$GNRMC')):
                        pt = parse_gprmc(line)
                        if pt:
                            self.point_received.emit(pt)

        except Exception as exc:
            if self._running:
                msg  = str(exc)
                hint = serial_error_hint(exc, self._port)
                self.error_occurred.emit(f'{msg}\n\n{hint}' if hint else msg)

        self._running = False
