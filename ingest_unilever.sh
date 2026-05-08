#!/usr/bin/env bash
# ─── Unilever PDF Batch Ingest ───────────────────────────────────────────────
# Usage:  ./ingest_unilever.sh [backend_url]
#
# Calls POST /api/ingest for each of the 5 Unilever FY2x PDFs in static/.
# Requires the FastAPI backend to be running (default: http://localhost:8000).
#
# Prerequisites:
#   1. Start backend:  uvicorn backend.main:app --host 0.0.0.0 --port 8000
#   2. Then run:        ./ingest_unilever.sh
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BACKEND_URL="${1:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATIC_DIR="$SCRIPT_DIR/static"

# Ordered list of (filename, year_period) pairs
FILES=(
  "Unilever - FY23.pdf|2023"
  "Unilever - FY24.pdf|2024"
  "Unilever - FY25.pdf|2025"
)

COMPANY="Unilever"
FAILED=0

echo "============================================"
echo " Unilever PDF Batch Ingest"
echo " Backend: $BACKEND_URL"
echo " Company: $COMPANY"
echo "============================================"

for entry in "${FILES[@]}"; do
  filename="${entry%%|*}"
  year="${entry##*|}"
  filepath="$STATIC_DIR/$filename"

  if [[ ! -f "$filepath" ]]; then
    echo "[SKIP] File not found: $filepath"
    FAILED=$((FAILED + 1))
    continue
  fi

  echo ""
  echo "--- Ingesting: $filename ($year) ---"
  echo "    File: $filepath"

  http_code=$(curl -s -o /tmp/ingest_response.json -w "%{http_code}" \
    -X POST "$BACKEND_URL/api/ingest" \
    -H "Content-Type: application/json" \
    -d "{
      \"file_path\": \"$filepath\",
      \"company_name\": \"$COMPANY\",
      \"year_period\": \"$year\"
    }")

  if [[ "$http_code" == "200" ]]; then
    doc_pk=$(python3 -c "import json; print(json.load(open('/tmp/ingest_response.json')).get('doc_pk','?'))" 2>/dev/null || echo "?")
    node_count=$(python3 -c "import json; print(json.load(open('/tmp/ingest_response.json')).get('node_count','?'))" 2>/dev/null || echo "?")
    echo "    [OK] HTTP $http_code  doc_pk=$doc_pk  nodes=$node_count"
  else
    echo "    [FAIL] HTTP $http_code"
    cat /tmp/ingest_response.json 2>/dev/null || true
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "============================================"
if [[ $FAILED -eq 0 ]]; then
  echo " All 5 files ingested successfully."
else
  echo " $FAILED file(s) failed. Check output above."
fi
echo "============================================"
