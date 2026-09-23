"""
lora_common.py — Utilitaires partagés par les trois points d'entrée LoRa
              (lora_receiver.py en ligne de commande, lora_thread.py côté
              interface, LoraConnectDialog dans dialogs.py).
Aucune dépendance Qt.
"""

import errno
import glob
import grp
import os
import pwd
import re
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


_RSSI_RE = re.compile(r'^#\s*\[(\d+)\]\s*RSSI:\s*(-?\d+)\s*dBm')


def parse_rssi_line(line: str):
    """Ligne de diagnostic du récepteur rf95_server « # [12] RSSI: -71 dBm »
    → (numéro de paquet, RSSI en dBm), ou None pour toute autre ligne."""
    m = _RSSI_RE.match(line.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def rssi_quality(rssi: int) -> str:
    """Appréciation du niveau de signal LoRa (SX1276, 433/868 MHz)."""
    if rssi >= -90:
        return 'bon'
    if rssi >= -110:
        return 'moyen'
    return 'faible'


def _error_errno(exc) -> int | None:
    """errno d'une erreur de port série (pyserial le met souvent dans le texte)."""
    code = getattr(exc, 'errno', None)
    if isinstance(code, int):
        return code
    m = re.search(r'\[Errno (\d+)\]', str(exc))
    return int(m.group(1)) if m else None


def _port_group(port: str) -> str:
    """Groupe propriétaire du périphérique (dialout sur Debian/Ubuntu, uucp sur Arch…)."""
    try:
        return grp.getgrgid(os.stat(port).st_gid).gr_name
    except (OSError, KeyError):
        return 'dialout'


def _user_in_group_config(group: str) -> bool:
    """L'utilisateur est-il déjà membre du groupe dans /etc/group
    (même si la session courante ne l'a pas encore pris en compte) ?"""
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
        g = grp.getgrnam(group)
        return user in g.gr_mem or pwd.getpwnam(user).pw_gid == g.gr_gid
    except KeyError:
        return False


def serial_error_hint(exc, port: str,
                      command: str = './runGPSLoRa.sh') -> str | None:
    """Conseil de résolution pour une erreur d'ouverture du port série,
    ou None si l'erreur n'est pas d'un type connu. `command` est la commande
    de lancement citée dans le conseil (appli ou récepteur en ligne de commande)."""
    code = _error_errno(exc)
    if code == errno.EACCES:
        group = _port_group(port)
        if _user_in_group_config(group):
            return (f"Vous êtes déjà membre du groupe « {group} », mais la session "
                    "actuelle ne l'a pas encore pris en compte : fermez puis "
                    "rouvrez votre session (ou redémarrez).\n\n"
                    "En attendant, relancez avec :\n"
                    f"    sg {group} -c {command}")
        return (f"Le port {port} n'est accessible qu'au groupe « {group} ». "
                "Ajoutez votre compte à ce groupe :\n"
                f"    sudo usermod -aG {group} $USER\n"
                "puis fermez et rouvrez votre session (ou redémarrez).\n\n"
                "Pour tester sans fermer la session :\n"
                f"    sg {group} -c {command}")
    if code == errno.EBUSY:
        return (f"Le port {port} est déjà utilisé par un autre programme "
                "(moniteur série de l'IDE Arduino, lora_receiver.py, autre "
                "instance de GPS Viewer…). Fermez-le puis réessayez.")
    if code == errno.ENOENT:
        return (f"Le port {port} n'existe pas : vérifiez que l'Arduino est "
                "branché (câble USB de données, pas seulement d'alimentation) "
                "et que le port choisi est le bon.")
    return None
