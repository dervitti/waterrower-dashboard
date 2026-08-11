#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo "python3 fehlt. Installieren z.B.: sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
echo "Python: $(python3 --version)"

if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_MINOR" -lt 10 ]; then
  echo "Dieses Projekt braucht Python 3.10–3.13."
  echo "Unter Arch: sudo pacman -S python312 && python3.12 -m venv .venv"
  echo "Unter Ubuntu: sudo apt install python3.12 python3.12-venv"
  exit 1
fi

if [ "$PY_MINOR" -ge 14 ]; then
  echo "Warnung: Python $PY_MAJOR.$PY_MINOR ist oft zu neu für die Dependencies."
  echo "Bitte Python 3.12 verwenden, z.B. unter Arch:"
  echo "  sudo pacman -S python312"
  echo "  rm -rf .venv && python3.12 -m venv .venv"
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo
echo "OK. Start mit:"
echo "  source .venv/bin/activate"
echo "  uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo "oder: ./run.sh"
