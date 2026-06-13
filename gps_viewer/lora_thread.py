"""
lora_thread.py — QThread de réception GPS série (LoRa / NMEA)
             Lit le port série, émet un signal par point GPGGA valide,
             et sauvegarde toutes les trames NMEA dans un fichier.
"""

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from gps_nmea import parse_gpgga

BAUD_RATE_DEFAULT = 115_200


def default_lora_output_path() -> Path:
    """Génère un chemin horodaté dans tracks/gps/."""
    tracks_dir = Path(__file__).parent / 'tracks' / 'gps'
    tracks_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return tracks_dir / f'LORA_{ts}.txt'


class LoraThread(QThread):
    """Lit le port série en arrière-plan et émet les points GPS valides."""

    # Point GPGGA parsé : dict avec lat, lon, alt, time, sats, hdop
    point_received = pyqtSignal(dict)
    # Erreur fatale (port inaccessible, déconnexion…)
    error_occurred = pyqtSignal(str)

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

                    line = raw.decode('ascii', errors='replace').rstrip()

                    # Toutes les trames NMEA sont sauvegardées
                    if line.startswith('$'):
                        f.write(line + '\r\n')
                        f.flush()

                    # Seules les GPGGA valides déclenchent un point sur la carte
                    if line.startswith('$GPGGA'):
                        pt = parse_gpgga(line)
                        if pt:
                            self.point_received.emit(pt)

        except Exception as exc:
            if self._running:
                self.error_occurred.emit(str(exc))

        self._running = False
