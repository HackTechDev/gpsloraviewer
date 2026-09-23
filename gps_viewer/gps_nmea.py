"""
gps_nmea.py — Parsing NMEA, utilitaires géo, classe GPSData
Aucune dépendance Qt ni matplotlib.
"""

import math
import os
import datetime
from pathlib import Path

import numpy as np

# ── Constante géo ────────────────────────────────────────────────────
WEB_MERC_R = 6_378_137.0


# ══════════════════════════════════════════════════════════════════════
#  Utilitaires GPS
# ══════════════════════════════════════════════════════════════════════

def verify_checksum(line: str) -> bool:
    """Vérifie le checksum NMEA en fin de trame (XOR entre '$' et '*').

    Retourne False si le checksum est absent, mal formé, ou ne correspond
    pas à la valeur calculée — ce qui permet de rejeter silencieusement les
    trames corrompues (bruit radio en particulier avec la réception LoRa).
    """
    line = line.strip()
    if not line.startswith('$'):
        return False
    star = line.find('*')
    if star == -1 or star + 3 > len(line):
        return False
    checksum = 0
    for ch in line[1:star]:
        checksum ^= ord(ch)
    try:
        return checksum == int(line[star + 1:star + 3], 16)
    except ValueError:
        return False


def nmea_to_decimal(coord: str, direction: str) -> float:
    dot = coord.index('.')
    deg = int(coord[:dot - 2])
    minutes = float(coord[dot - 2:])
    v = deg + minutes / 60.0
    return -v if direction in ('S', 'W') else v


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def parse_time_s(time_str: str):
    try:
        t = time_str.replace(' UTC', '')
        h, m, s = t.split(':')
        return int(h)*3600 + int(m)*60 + float(s)
    except Exception:
        return None


def speed_kmh_between(p0: dict, p1: dict) -> float | None:
    """Vitesse moyenne (km/h) entre deux points {lat, lon, time 'HH:MM:SS[.ss] UTC'},
    ou None si l'écart de temps est inconnu ou nul."""
    t0, t1 = parse_time_s(p0.get('time', '')), parse_time_s(p1.get('time', ''))
    if t0 is None or t1 is None:
        return None
    dt = t1 - t0
    if dt < 0:
        dt += 86_400                         # passage de minuit UTC
    if dt <= 0:
        return None
    return haversine_m(p0['lat'], p0['lon'], p1['lat'], p1['lon']) / dt * 3.6


def _smooth(data: list, window: int = 5) -> list:
    hw = window // 2
    out = []
    for i in range(len(data)):
        vals = [data[j] for j in range(max(0, i-hw), min(len(data), i+hw+1))
                if data[j] is not None]
        out.append(sum(vals)/len(vals) if vals else None)
    return out


def parse_gprmc(line: str):
    """Parse une trame $GPRMC ou $GNRMC. Retourne None si fix invalide
    ou si le checksum ne correspond pas (trame corrompue)."""
    if not verify_checksum(line):
        return None
    parts = line.strip().split(',')
    if len(parts) < 7:
        return None
    try:
        raw_t  = parts[1]
        status = parts[2]
        if status != 'A':
            return None
        if not parts[3] or not parts[5]:
            return None
        lat = nmea_to_decimal(parts[3], parts[4])
        lon = nmea_to_decimal(parts[5], parts[6])
    except (ValueError, IndexError):
        return None
    fmt = (f"{raw_t[0:2]}:{raw_t[2:4]}:{raw_t[4:]} UTC"
           if len(raw_t) >= 6 else raw_t)
    return {'time': fmt, 'lat': lat, 'lon': lon,
            'alt': None, 'sats': 0, 'hdop': None}


def parse_gpgga(line: str):
    """Parse une trame $GPGGA ou $GNGGA. Retourne None si fix invalide
    ou si le checksum ne correspond pas (trame corrompue)."""
    if not verify_checksum(line):
        return None
    parts = line.strip().split(',')
    if len(parts) < 10:
        return None
    try:
        raw_t  = parts[1]
        fix    = int(parts[6]) if parts[6] else 0
        sats   = int(parts[7]) if parts[7] else 0
        hdop   = float(parts[8]) if parts[8] else None
        alt    = float(parts[9]) if parts[9] else None
    except (ValueError, IndexError):
        return None
    if fix == 0 or not parts[2] or not parts[4]:
        return None
    try:
        lat = nmea_to_decimal(parts[2], parts[3])
        lon = nmea_to_decimal(parts[4], parts[5])
    except (ValueError, IndexError):
        return None
    fmt = (f"{raw_t[0:2]}:{raw_t[2:4]}:{raw_t[4:]} UTC"
           if len(raw_t) >= 6 else raw_t)
    return {'time': fmt, 'lat': lat, 'lon': lon,
            'alt': alt, 'sats': sats, 'hdop': hdop}


def decode_nmea_fields(line: str) -> dict | None:
    """Décode les champs d'une trame RMC ou GGA *même sans fix GPS*, pour
    l'affichage (moniteur de réception). Contrairement à parse_gprmc /
    parse_gpgga, ne rejette pas les trames sans position : renvoie ce qui est
    présent (clés absentes si le champ est vide). None si la trame n'est ni
    RMC ni GGA, ou si son checksum est invalide.

    Clés possibles : type ('RMC'/'GGA'), time, date, fix (bool), lat, lon,
    speed_kmh, course, alt, sats, hdop.
    """
    if not verify_checksum(line):
        return None
    body  = line.strip()[1:line.strip().find('*')]
    parts = body.split(',')
    kind  = parts[0][2:] if len(parts[0]) == 5 else ''
    if kind not in ('RMC', 'GGA'):
        return None
    out = {'type': kind}

    def _set(key, fn):
        try:
            v = fn()
        except (ValueError, IndexError):
            return
        if v is not None:
            out[key] = v

    def _time(raw):
        return f'{raw[0:2]}:{raw[2:4]}:{raw[4:6]}' if len(raw) >= 6 else None

    def _date(raw):
        # ddmmyy ; siècle selon la convention NMEA (yy < 80 → 20yy)
        if len(raw) != 6:
            return None
        yy = int(raw[4:6])
        return f'{raw[0:2]}/{raw[2:4]}/{2000 + yy if yy < 80 else 1900 + yy}'

    def _latlon(i):
        return (nmea_to_decimal(parts[i], parts[i + 1]),
                nmea_to_decimal(parts[i + 2], parts[i + 3]))

    _set('time', lambda: _time(parts[1]))
    if kind == 'RMC':
        out['fix'] = len(parts) > 2 and parts[2] == 'A'
        _set('pos', lambda: _latlon(3) if parts[3] and parts[5] else None)
        _set('speed_kmh', lambda: float(parts[7]) * 1.852 if parts[7] else None)
        _set('course', lambda: float(parts[8]) if parts[8] else None)
        _set('date', lambda: _date(parts[9]))
    else:
        _set('fix', lambda: int(parts[6] or 0) > 0)
        out.setdefault('fix', False)
        _set('pos', lambda: _latlon(2) if parts[2] and parts[4] else None)
        _set('sats', lambda: int(parts[7]) if parts[7] else None)
        _set('hdop', lambda: float(parts[8]) if parts[8] else None)
        _set('alt', lambda: float(parts[9]) if parts[9] else None)
    if 'pos' in out:
        out['lat'], out['lon'] = out.pop('pos')
    return out


def load_points(filepath: str) -> list:
    pts = []
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            if line.startswith(('$GPGGA', '$GNGGA')):
                pt = parse_gpgga(line)
                if pt:
                    pts.append(pt)
            elif line.startswith(('$GPRMC', '$GNRMC')):
                pt = parse_gprmc(line)
                if pt:
                    pts.append(pt)
    return pts


def _fmt_dist(d: float) -> str:
    """Formate une distance : km si ≥ 1 000 m, sinon mètres."""
    return f'{d / 1000:.1f} km' if d >= 1000 else f'{d:.0f} m'


def _fmt_elapsed(s: float) -> str:
    """Formate un temps écoulé en secondes → 'Xh YYmin' ou 'Ymin'."""
    m = int(s // 60)
    h = m // 60
    return f'{h}h {m % 60:02d}min' if h else f'{m} min'


def to_webmerc(lat: float, lon: float):
    x = math.radians(lon) * WEB_MERC_R
    y = math.log(math.tan(math.radians(lat)/2 + math.pi/4)) * WEB_MERC_R
    return x, y


def _webmerc_to_latlon(x: float, y: float):
    lon = math.degrees(x / WEB_MERC_R)
    lat = math.degrees(2 * math.atan(math.exp(y / WEB_MERC_R)) - math.pi / 2)
    return lat, lon


# ══════════════════════════════════════════════════════════════════════
#  Modèle de données
# ══════════════════════════════════════════════════════════════════════

class GPSData:
    def __init__(self, points: list, filepath: str):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.points   = points
        n = len(points)

        # Distances cumulées (m)
        self.distances = [0.0]
        for i in range(1, n):
            self.distances.append(self.distances[-1] + haversine_m(
                points[i-1]['lat'], points[i-1]['lon'],
                points[i]['lat'],   points[i]['lon']))
        self.total_dist = self.distances[-1]

        # Altitudes
        self.alts = [p['alt'] for p in points]
        valid_a = [a for a in self.alts if a is not None]
        self.alt_min = min(valid_a) if valid_a else None
        self.alt_max = max(valid_a) if valid_a else None
        self.alt_avg = sum(valid_a)/len(valid_a) if valid_a else None

        # Gain/perte altimétrique D+ / D− (seuil 3 m pour filtrer le bruit GPS)
        if valid_a:
            _THRESH = 3.0
            dp = dm = 0.0
            ref = self.alts[0]
            for a in self.alts[1:]:
                if a is None:
                    continue
                if ref is None:
                    ref = a
                    continue
                diff = a - ref
                if diff >= _THRESH:
                    dp += diff
                    ref = a
                elif diff <= -_THRESH:
                    dm += abs(diff)
                    ref = a
            self.elev_gain: float | None = dp
            self.elev_loss: float | None = dm
        else:
            self.elev_gain = None
            self.elev_loss = None

        # Vitesses (km/h), lissées
        raw_spd = [None]
        for i in range(1, n):
            t1 = parse_time_s(points[i-1]['time'])
            t2 = parse_time_s(points[i]['time'])
            dd = self.distances[i] - self.distances[i-1]
            if t1 is not None and t2 is not None:
                dt = t2 - t1
                if dt < 0:
                    dt += 86400
                raw_spd.append(dd / dt * 3.6 if dt > 0 else None)
            else:
                raw_spd.append(None)
        self.speeds = _smooth(raw_spd, window=5)
        valid_s = [s for s in self.speeds if s is not None]
        self.spd_max = max(valid_s) if valid_s else 0.0
        self.spd_avg = sum(valid_s)/len(valid_s) if valid_s else 0.0

        # Durée + temps écoulé par point
        t0 = parse_time_s(points[0]['time'])
        tN = parse_time_s(points[-1]['time'])
        self.duration_s = None
        if t0 is not None and tN is not None:
            d = tN - t0
            self.duration_s = d + 86400 if d < 0 else d
        if t0 is not None:
            elapsed = []
            for p in points:
                t = parse_time_s(p['time'])
                if t is None:
                    elapsed.append(None)
                else:
                    e = t - t0
                    elapsed.append(e + 86400 if e < 0 else e)
            self.elapsed_times: list = elapsed
        else:
            self.elapsed_times = [None] * n

        # Coordonnées Web Mercator (numpy)
        wm = [to_webmerc(p['lat'], p['lon']) for p in points]
        self.xs = np.array([w[0] for w in wm])
        self.ys = np.array([w[1] for w in wm])
        self.dist_arr = np.array(self.distances)

    @property
    def count(self) -> int:
        return len(self.points)
