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
import argparse
from pathlib import Path

try:
    import serial
except ImportError:
    print("Erreur : pyserial non installé.")
    print("  pip install pyserial")
    sys.exit(1)

from gps_nmea import verify_checksum
from lora_common import (detect_port, default_lora_output_path, BAUD_RATE_DEFAULT,
                         serial_error_hint)

BAUD_RATE = BAUD_RATE_DEFAULT


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

    out_path = Path(args.output) if args.output else default_lora_output_path()

    print(f"Port    : {port} @ {BAUD_RATE} baud")
    print(f"Fichier : {out_path}")
    print("En attente de trames NMEA... (Ctrl+C pour arrêter)\n")

    nmea_count = 0
    rejected_count = 0

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
                # au checksum valide (rejette les trames corrompues par le
                # bruit radio de la liaison LoRa)
                if line.startswith('$'):
                    if verify_checksum(line):
                        f.write(line + '\r\n')
                        f.flush()
                        nmea_count += 1
                    else:
                        rejected_count += 1

    except serial.SerialException as e:
        print(f"\nErreur port série : {e}")
        hint = serial_error_hint(e, port, command='./runLoRaReceiver.sh')
        if hint:
            print(f"\n{hint}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\nArrêt — {nmea_count} trames NMEA enregistrées dans {out_path}"
              + (f"  ({rejected_count} rejetée(s), checksum invalide)"
                 if rejected_count else ""))


if __name__ == '__main__':
    main()
