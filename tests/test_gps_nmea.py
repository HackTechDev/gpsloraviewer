"""
Tests de gps_nmea.py — parseur NMEA, checksum, géométrie, formatage.
Toutes ces fonctions sont pures (aucune dépendance Qt/matplotlib), donc
testables sans interface graphique.
"""

import math
import pytest

from gps_nmea import (
    verify_checksum, nmea_to_decimal, haversine_m, parse_time_s, _smooth,
    parse_gprmc, parse_gpgga, load_points, to_webmerc, _webmerc_to_latlon,
    _fmt_dist, _fmt_elapsed, GPSData,
)

# Trames de référence (exemples classiques du standard NMEA 0183)
GOOD_RMC = '$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A'
GOOD_GGA = '$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47'


# ── Checksum ─────────────────────────────────────────────────────────

def test_verify_checksum_valid():
    assert verify_checksum(GOOD_RMC) is True
    assert verify_checksum(GOOD_GGA) is True


def test_verify_checksum_invalid():
    corrupted = GOOD_RMC[:-2] + '00'
    assert verify_checksum(corrupted) is False


def test_verify_checksum_missing_star():
    assert verify_checksum('$GPRMC,123519,A,4807.038,N,01131.000,E') is False


def test_verify_checksum_missing_dollar():
    assert verify_checksum('GPRMC,123519,A*6A') is False


def test_verify_checksum_tolerates_surrounding_whitespace():
    assert verify_checksum(GOOD_RMC + '\r\n') is True


# ── Conversions géographiques ────────────────────────────────────────

def test_nmea_to_decimal_north():
    assert nmea_to_decimal('4807.038', 'N') == pytest.approx(48.1173, abs=1e-4)


def test_nmea_to_decimal_south_is_negative():
    assert nmea_to_decimal('4807.038', 'S') == pytest.approx(-48.1173, abs=1e-4)


def test_haversine_zero_distance():
    assert haversine_m(48.85, 2.35, 48.85, 2.35) == 0.0


def test_haversine_paris_lyon():
    # Distance à vol d'oiseau Paris-Lyon ≈ 391-392 km
    d = haversine_m(48.8566, 2.3522, 45.7640, 4.8357)
    assert 390_000 < d < 393_000


def test_to_webmerc_roundtrip():
    lat, lon = 48.8566, 2.3522
    x, y = to_webmerc(lat, lon)
    lat2, lon2 = _webmerc_to_latlon(x, y)
    assert lat2 == pytest.approx(lat, abs=1e-9)
    assert lon2 == pytest.approx(lon, abs=1e-9)


# ── Temps ────────────────────────────────────────────────────────────

def test_parse_time_s_valid():
    assert parse_time_s('12:35:19 UTC') == 12 * 3600 + 35 * 60 + 19


def test_parse_time_s_invalid_returns_none():
    assert parse_time_s('pas une heure') is None


# ── Lissage ──────────────────────────────────────────────────────────

def test_smooth_averages_window():
    assert _smooth([1, 2, 3, 4, 5], window=3) == [1.5, 2.0, 3.0, 4.0, 4.5]


def test_smooth_ignores_none():
    result = _smooth([1, None, 3], window=3)
    assert result[1] == pytest.approx(2.0)


def test_smooth_all_none():
    assert _smooth([None, None], window=3) == [None, None]


# ── Formatage ────────────────────────────────────────────────────────

@pytest.mark.parametrize('meters, expected', [
    (500, '500 m'),
    (999, '999 m'),
    (1000, '1.0 km'),
    (12345, '12.3 km'),
])
def test_fmt_dist(meters, expected):
    assert _fmt_dist(meters) == expected


@pytest.mark.parametrize('seconds, expected', [
    (59, '0 min'),
    (600, '10 min'),
    (3661, '1h 01min'),
    (7384, '2h 03min'),
])
def test_fmt_elapsed(seconds, expected):
    assert _fmt_elapsed(seconds) == expected


# ── Parsing de trames ────────────────────────────────────────────────

def test_parse_gprmc_valid():
    pt = parse_gprmc(GOOD_RMC)
    assert pt is not None
    assert pt['lat'] == pytest.approx(48.1173, abs=1e-4)
    assert pt['lon'] == pytest.approx(11.516666, abs=1e-4)
    assert pt['time'] == '12:35:19 UTC'


def test_parse_gprmc_bad_checksum_rejected():
    corrupted = GOOD_RMC[:-2] + '00'
    assert parse_gprmc(corrupted) is None


def test_parse_gprmc_invalid_status_rejected():
    invalid_status = GOOD_RMC.replace(',A,', ',V,')
    # Le statut change, il faut recalculer le checksum pour isoler le cas testé
    payload = invalid_status[1:invalid_status.index('*')]
    checksum = 0
    for ch in payload:
        checksum ^= ord(ch)
    invalid_status = f'{invalid_status[:invalid_status.index("*")]}*{checksum:02X}'
    assert parse_gprmc(invalid_status) is None


def test_parse_gpgga_valid():
    pt = parse_gpgga(GOOD_GGA)
    assert pt is not None
    assert pt['alt'] == pytest.approx(545.4)
    assert pt['sats'] == 8
    assert pt['hdop'] == pytest.approx(0.9)


def test_parse_gpgga_bad_checksum_rejected():
    corrupted = GOOD_GGA[:-2] + '00'
    assert parse_gpgga(corrupted) is None


def test_parse_gpgga_fix_quality_zero_rejected():
    no_fix = GOOD_GGA.replace(',1,08,', ',0,08,')
    payload = no_fix[1:no_fix.index('*')]
    checksum = 0
    for ch in payload:
        checksum ^= ord(ch)
    no_fix = f'{no_fix[:no_fix.index("*")]}*{checksum:02X}'
    assert parse_gpgga(no_fix) is None


def test_parse_gprmc_too_few_fields():
    assert parse_gprmc('$GPRMC,123519*00') is None


# ── Lecture de fichier ───────────────────────────────────────────────

def test_load_points_filters_invalid_and_corrupted(tmp_path):
    corrupted = GOOD_GGA[:-2] + '00'
    f = tmp_path / 'trace.txt'
    f.write_text('\n'.join([
        GOOD_GGA,       # valide
        corrupted,      # checksum invalide -> rejeté
        GOOD_RMC,       # valide
        '# ligne de diagnostic RSSI, pas une trame NMEA',
    ]) + '\n')
    points = load_points(str(f))
    assert len(points) == 2


# ── Modèle GPSData ───────────────────────────────────────────────────

def _make_point(lat, lon, alt, t):
    return {'time': t, 'lat': lat, 'lon': lon, 'alt': alt, 'sats': 6, 'hdop': 1.0}


def test_gpsdata_basic_stats():
    points = [
        _make_point(48.8566, 2.3522, 100.0, '12:00:00 UTC'),
        _make_point(48.8576, 2.3522, 110.0, '12:00:10 UTC'),
        _make_point(48.8586, 2.3522, 95.0,  '12:00:20 UTC'),
    ]
    gps = GPSData(points, '/tmp/fake.txt')
    assert gps.count == 3
    assert gps.filename == 'fake.txt'
    assert gps.total_dist > 0
    assert gps.alt_min == 95.0
    assert gps.alt_max == 110.0
    assert gps.duration_s == 20.0


def test_gpsdata_elevation_gain_loss_thresholded():
    # Variations < 3 m ignorées (bruit GPS) ; ici 10 m de montée puis 15 m de descente
    points = [
        _make_point(48.85, 2.35, 100.0, '12:00:00 UTC'),
        _make_point(48.86, 2.35, 110.0, '12:00:10 UTC'),
        _make_point(48.87, 2.35, 95.0,  '12:00:20 UTC'),
    ]
    gps = GPSData(points, '/tmp/fake.txt')
    assert gps.elev_gain == pytest.approx(10.0)
    assert gps.elev_loss == pytest.approx(15.0)


# ── decode_nmea_fields (moniteur de réception LoRa) ──────────────────────

from gps_nmea import decode_nmea_fields   # noqa: E402

NOFIX_RMC = '$GPRMC,000243.800,V,,,,,0.00,0.00,060180,,,N*4F'


def test_decode_rmc_without_fix_keeps_time_and_date():
    f = decode_nmea_fields(NOFIX_RMC)
    assert f['type'] == 'RMC' and f['fix'] is False
    assert f['time'] == '00:02:43'
    assert f['date'] == '06/01/1980'          # yy ≥ 80 → 19yy
    assert 'lat' not in f and 'lon' not in f


def test_decode_rmc_with_fix():
    f = decode_nmea_fields(GOOD_RMC)
    assert f['fix'] is True
    assert f['lat'] == pytest.approx(48.1173)
    assert f['lon'] == pytest.approx(11.516667, abs=1e-6)
    assert f['speed_kmh'] == pytest.approx(22.4 * 1.852)
    assert f['course'] == pytest.approx(84.4)
    assert f['date'] == '23/03/1994'


def test_decode_gga():
    f = decode_nmea_fields(GOOD_GGA)
    assert f['type'] == 'GGA' and f['fix'] is True
    assert (f['sats'], f['hdop'], f['alt']) == (8, 0.9, 545.4)


@pytest.mark.parametrize('line', [
    '$GPRMC,000116.7',                                   # tronquée
    GOOD_RMC[:-2] + '00',                                # mauvais checksum
    '$GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00*74',
    '# [3] RSSI: -71 dBm',
])
def test_decode_rejects_other_lines(line):
    assert decode_nmea_fields(line) is None


# ── speed_kmh_between (vitesse affichée sur la trace LoRa Live) ─────────

from gps_nmea import speed_kmh_between   # noqa: E402


def test_speed_between_points():
    p0 = {'lat': 48.0, 'lon': 7.0, 'time': '12:00:00.00 UTC'}
    p1 = {'lat': 48.0 + 100 / 111_195, 'lon': 7.0, 'time': '12:00:10.00 UTC'}  # ~100 m en 10 s
    assert speed_kmh_between(p0, p1) == pytest.approx(36.0, rel=1e-3)


def test_speed_across_midnight():
    p0 = {'lat': 48.0, 'lon': 7.0, 'time': '23:59:55 UTC'}
    p1 = {'lat': 48.0 + 100 / 111_195, 'lon': 7.0, 'time': '00:00:05 UTC'}
    assert speed_kmh_between(p0, p1) == pytest.approx(36.0, rel=1e-3)


@pytest.mark.parametrize('t1', ['12:00:00 UTC', '', 'n/a'])
def test_speed_unknown_or_zero_interval(t1):
    p0 = {'lat': 48.0, 'lon': 7.0, 'time': '12:00:00 UTC'}
    assert speed_kmh_between(p0, {'lat': 48.1, 'lon': 7.0, 'time': t1}) is None
