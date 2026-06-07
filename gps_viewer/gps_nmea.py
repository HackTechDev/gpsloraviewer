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


def _smooth(data: list, window: int = 5) -> list:
    hw = window // 2
    out = []
    for i in range(len(data)):
        vals = [data[j] for j in range(max(0, i-hw), min(len(data), i+hw+1))
                if data[j] is not None]
        out.append(sum(vals)/len(vals) if vals else None)
    return out


def parse_gpgga(line: str):
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


def load_points(filepath: str) -> list:
    pts = []
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            if line.startswith('$GPGGA'):
                pt = parse_gpgga(line)
                if pt:
                    pts.append(pt)
    return pts


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
