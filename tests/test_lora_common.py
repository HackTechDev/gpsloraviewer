"""
Tests de lora_common.serial_error_hint — conseils affichés quand le port
série du récepteur LoRa ne peut pas être ouvert (fonction pure, sans Qt).
"""

import errno

import pytest

import lora_common
from lora_common import serial_error_hint


class FakeSerialException(OSError):
    """Imite serial.SerialException : errno dans .errno et dans le texte."""


def _perm_error():
    return FakeSerialException(
        errno.EACCES, "could not open port /dev/ttyUSB0: [Errno 13] "
                      "Permission denied: '/dev/ttyUSB0'")


@pytest.fixture
def group_uucp(monkeypatch):
    monkeypatch.setattr(lora_common, '_port_group', lambda port: 'uucp')


def test_permission_user_not_in_group(monkeypatch, group_uucp):
    monkeypatch.setattr(lora_common, '_user_in_group_config', lambda g: False)
    hint = serial_error_hint(_perm_error(), '/dev/ttyUSB0')
    assert 'sudo usermod -aG uucp $USER' in hint
    assert 'sg uucp -c ./runGPSLoRa.sh' in hint


def test_permission_user_in_group_needs_relogin(monkeypatch, group_uucp):
    monkeypatch.setattr(lora_common, '_user_in_group_config', lambda g: True)
    hint = serial_error_hint(_perm_error(), '/dev/ttyUSB0',
                             command='./runLoRaReceiver.sh')
    assert 'usermod' not in hint
    assert 'déjà membre du groupe « uucp »' in hint
    assert 'sg uucp -c ./runLoRaReceiver.sh' in hint


def test_errno_parsed_from_message_only(monkeypatch, group_uucp):
    # pyserial ne renseigne pas toujours .errno : on le lit dans le texte
    monkeypatch.setattr(lora_common, '_user_in_group_config', lambda g: False)
    exc = Exception("[Errno 13] could not open port /dev/ttyUSB0: "
                    "[Errno 13] Permission non accordée: '/dev/ttyUSB0'")
    assert 'usermod' in serial_error_hint(exc, '/dev/ttyUSB0')


@pytest.mark.parametrize('code, expected', [
    (errno.EBUSY,  'déjà utilisé'),
    (errno.ENOENT, "n'existe pas"),
])
def test_other_known_errors(code, expected):
    hint = serial_error_hint(FakeSerialException(code, 'x'), '/dev/ttyUSB0')
    assert expected in hint


def test_unknown_error_gives_no_hint():
    assert serial_error_hint(Exception('device reports readiness to read '
                                       'but returned no data'), '/dev/ttyUSB0') is None


def test_port_group_fallback_when_port_missing():
    assert lora_common._port_group('/dev/nexistepas') == 'dialout'


# ── Lignes de diagnostic du récepteur (rf95_server.ino) ─────────────────

from lora_common import parse_rssi_line, rssi_quality   # noqa: E402


def test_parse_rssi_line():
    assert parse_rssi_line('# [12] RSSI: -71 dBm') == (12, -71)
    assert parse_rssi_line('# [3] RSSI: -113 dBm\r') == (3, -113)


@pytest.mark.parametrize('line', ['# LoRa OK @ 433.0 MHz', '# recv failed',
                                  '$GPRMC,000243.800,V,,,,,0.00,0.00,060180,,,N*4F'])
def test_parse_rssi_line_ignores_other_lines(line):
    assert parse_rssi_line(line) is None


@pytest.mark.parametrize('rssi, q', [(-60, 'bon'), (-90, 'bon'), (-91, 'moyen'),
                                     (-110, 'moyen'), (-111, 'faible')])
def test_rssi_quality(rssi, q):
    assert rssi_quality(rssi) == q
