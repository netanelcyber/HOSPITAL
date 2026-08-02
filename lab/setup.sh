#!/usr/bin/env bash
# Provision the local Wordfence lab: bring up containers, install WordPress,
# create users, and install/activate Wordfence.
# AUTHORIZED LOCAL LAB USE ONLY.
set -euo pipefail

cd "$(dirname "$0")"

SITE_URL="http://127.0.0.1:8080"

echo "[*] Starting containers..."
docker compose up -d db wordpress wpcli

echo "[*] Waiting for WordPress/DB to become ready..."
for i in $(seq 1 30); do
  if docker compose exec -T wpcli wp core is-installed --allow-root >/dev/null 2>&1; then
    break
  fi
  if docker compose exec -T wpcli wp db check --allow-root >/dev/null 2>&1; then
    break
  fi
  sleep 3
done

echo "[*] Installing WordPress core..."
docker compose exec -T wpcli wp core install \
  --url="$SITE_URL" \
  --title="Hospital Lab" \
  --admin_user="admin" \
  --admin_password="admin123!" \
  --admin_email="admin@example.test" \
  --skip-email --allow-root || echo "[i] core already installed"

echo "[*] Creating extra users (for enumeration testing)..."
docker compose exec -T wpcli wp user create editor editor@example.test \
  --role=editor --user_pass="editorpass" --allow-root || true
docker compose exec -T wpcli wp user create author author@example.test \
  --role=author --user_pass="authorpass" --allow-root || true

echo "[*] Installing and activating Wordfence..."
docker compose exec -T wpcli wp plugin install wordfence --activate --allow-root || \
  echo "[!] Wordfence install failed (network?). Install manually via wp-admin."

echo "[*] Enabling pretty permalinks..."
docker compose exec -T wpcli wp rewrite structure '/%postname%/' --allow-root || true

echo
echo "[+] Lab ready:"
echo "    Site:  $SITE_URL"
echo "    Admin: $SITE_URL/wp-admin  (admin / admin123!)"
echo
echo "    Run recon:  python3 ../toolkit/wfrecon.py $SITE_URL"
