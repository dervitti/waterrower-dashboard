#!/usr/bin/env bash
# WaterRower Dashboard starten: venv → Server → Browser
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

HOST="${WR_HOST:-0.0.0.0}"
PORT="${WR_PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "venv fehlt oder Dependencies nicht installiert."
  echo "Bitte zuerst: bash setup.sh"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "=== WaterRower Dashboard ==="
echo "venv:   $VIRTUAL_ENV"
echo "URL:    $URL"
echo "Stoppen: Ctrl+C"
echo

# Server im Hintergrund, damit wir den Browser öffnen können
.venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" &
SERVER_PID=$!

cleanup() {
  echo
  echo "Stoppe Server (PID $SERVER_PID)…"
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Warten bis HTTP antwortet
echo -n "Warte auf Server"
for _ in $(seq 1 50); do
  if curl -sf "$URL/api/version" >/dev/null 2>&1 || curl -sf "$URL/" >/dev/null 2>&1; then
    echo " — bereit."
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo
    echo "Server ist abgestürzt — siehe Ausgabe oben."
    exit 1
  fi
  echo -n "."
  sleep 0.2
done

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  elif command -v gio >/dev/null 2>&1; then
    gio open "$URL" >/dev/null 2>&1 || true
  elif command -v firefox >/dev/null 2>&1; then
    firefox --new-tab "$URL" >/dev/null 2>&1 &
  elif command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser "$URL" >/dev/null 2>&1 &
  elif command -v google-chrome >/dev/null 2>&1; then
    google-chrome "$URL" >/dev/null 2>&1 &
  else
    echo "Kein Browser-Launcher gefunden — bitte öffnen: $URL"
    return
  fi
  echo "Browser: $URL"
}

open_browser

# Vordergrund: warten bis uvicorn endet
wait "$SERVER_PID"
