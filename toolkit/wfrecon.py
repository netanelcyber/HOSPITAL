#!/usr/bin/env python3
"""Launcher for the wfrecon toolkit (Python 3.5+).

Usage:
    python3 wfrecon.py http://127.0.0.1:8080
    python3 wfrecon.py http://127.0.0.1:8080 -m fingerprint,cve --json out.json
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wfrecon.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
