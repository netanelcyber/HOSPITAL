#!/usr/bin/env bash
# HTTP API property-fuzzing campaign (run from inside the fuzzer container).
# Requires an OpenAPI/Swagger spec from the Chameleon source or a live /openapi.json.
set -euo pipefail

TARGET="${TARGET:-http://chameleon.lab.internal}"
SPEC="${SPEC:-/work/campaigns/openapi.json}"   # drop the spec here, or use a URL
TOKEN="${LAB_TOKEN:-}"                          # lab auth token, if needed
OUT="/work/crashes/api"
mkdir -p "$OUT"

echo "[*] Fuzzing API at $TARGET using spec $SPEC"
schemathesis run \
  --checks all \
  --hypothesis-max-examples "${MAX:-500}" \
  ${TOKEN:+--header "Authorization: Bearer $TOKEN"} \
  --report "$OUT/schemathesis-report.tar.gz" \
  "$SPEC" 2>&1 | tee "$OUT/run.log"

echo "[*] Done. Findings + report in $OUT (send run.log back for triage)."
