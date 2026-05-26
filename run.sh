#!/usr/bin/env bash
cd "$(dirname "$0")"
exec python3 gps_viewer.py "$@"
