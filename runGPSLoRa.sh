#!/usr/bin/env bash
cd "$(dirname "$0")"
PYTHON=python3
[ -x .venv/bin/python ] && PYTHON=.venv/bin/python
exec "$PYTHON" gps_viewer/gps_viewer.py "$@"
