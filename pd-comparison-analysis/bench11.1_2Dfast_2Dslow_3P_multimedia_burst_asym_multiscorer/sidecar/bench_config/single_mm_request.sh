#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${ENDPOINT:-http://localhost:8080}"
PAYLOAD="${PAYLOAD:-./payload_http.json}"

curl -sS "${ENDPOINT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d @"${PAYLOAD}"
