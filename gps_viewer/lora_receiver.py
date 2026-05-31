#!/usr/bin/env python3
"""
lora_receiver.py — Lit le port série du récepteur LoRa (rf95_server)
et écrit les trames NMEA dans un fichier texte.

Utilisation :
    python3 lora_receiver.py
    python3 lora_receiver.py --port /dev/ttyUSB0
    python3 lora_receiver.py --port /dev/ttyUSB0 --output mon_fichier.txt

Dépendance : pip install pyserial
"""

import sys
import glob
import argparse
from datetime import datetime
from pathlib import Path

try:
    import serial
except ImportError:
    print("Erreur : pyserial non installé.")
    print("  pip install pyserial")
    sys.exit(1)


BAUD_RATE = 115200


def detect_port():
    """Retourne le premier port USB série disponible, ou None."""
    candidates = sorted(glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*'))
    return candidates[0] if candidates else None


def default_output_path():
    """Génère un chemin de sortie horodaté dans tracks/gps/."""
    tracks_dir = Path(__file__).parent / 'tracks' / 'gps'
    tracks_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return tracks_dir / f'LORA_{timestamp}.txt'


def main():
    parser = argparse.ArgumentParser(
        description='Récepteur LoRa — enregistre les trames NMEA reçues via le port série.'
    )
    parser.add_argument('--port', '-p',
                        help='Port série (ex: /dev/ttyUSB0). Détecté automatiquement si absent.')
    parser.add_argument('--output', '-o',
                        help='Fichier de sortie. Défaut : tracks/gps/LORA_YYYYMMDD_HHMMSS.txt')
    args = parser.parse_args()

    port = args.port or detect_port()
    if not port:
        print("Erreur : aucun port série détecté.")
        print("  Branchez l'Arduino récepteur et relancez, ou précisez --port /dev/ttyUSBx")
        sys.exit(1)

    out_path = Path(args.output) if args.output else default_output_path()

    print(f"Port    : {port} @ {BAUD_RATE} baud")
    print(f"Fichier : {out_path}")
    print("En attente de trames NMEA... (Ctrl+C pour arrêter)\n")

    nmea_count = 0

    try:
        with serial.Serial(port, BAUD_RATE, timeout=1) as ser, \
             open(out_path, 'w') as f:

            while True:
                raw = ser.readline()
                if not raw:
                    continue

                line = raw.decode('ascii', errors='replace').rstrip()

                # Affichage temps réel (trames NMEA + lignes # de diagnostic)
                print(line)

                # Écriture dans le fichier uniquement pour les trames NMEA
                if line.startswith('$'):
                    f.write(line + '\r\n')
                    f.flush()
                    nmea_count += 1

    except serial.SerialException as e:
        print(f"\nErreur port série : {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\nArrêt — {nmea_count} trames NMEA enregistrées dans {out_path}")


if __name__ == '__main__':
    main()
