#!/usr/bin/env bash
# Tear down the lab and remove volumes.
set -euo pipefail
cd "$(dirname "$0")"
docker compose down -v
echo "[+] Lab removed (containers + volumes)."
