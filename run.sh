#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "venv fehlt oder Dependencies nicht installiert."
  echo "Bitte zuerst: bash setup.sh"
  exit 1
fi

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
