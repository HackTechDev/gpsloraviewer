"""
lora_common.py — Utilitaires partagés par les trois points d'entrée LoRa
              (lora_receiver.py en ligne de commande, lora_thread.py côté
              interface, LoraConnectDialog dans dialogs.py).
Aucune dépendance Qt.
"""

import glob
from datetime import datetime
from pathlib import Path

BAUD_RATE_DEFAULT = 115_200


def detect_serial_ports() -> list:
    """Retourne les ports série USB détectés (/dev/ttyUSB*, /dev/ttyACM*)."""
    return sorted(glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*'))


def detect_port() -> str | None:
    """Retourne le premier port USB série disponible, ou None."""
    ports = detect_serial_ports()
    return ports[0] if ports else None


def default_lora_output_path() -> Path:
    """Génère un chemin de sortie horodaté dans tracks/gps/."""
    tracks_dir = Path(__file__).parent / 'tracks' / 'gps'
    tracks_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return tracks_dir / f'LORA_{timestamp}.txt'
