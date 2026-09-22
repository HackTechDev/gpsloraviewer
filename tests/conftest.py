"""Rend gps_viewer/ importable depuis les tests (pas de packaging du projet)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gps_viewer'))
