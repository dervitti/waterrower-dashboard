#!/usr/bin/env bash
# BlueZ-Cache für ComModule leeren (häufige Ursache für Sofort-Disconnect)
set -euo pipefail

echo "Gekoppelte/gesehene Geräte:"
bluetoothctl devices
echo
read -r -p "MAC-Adresse des ComModules (z.B. AA:BB:CC:DD:EE:FF): " MAC
if [[ -z "${MAC}" ]]; then
  echo "Keine Adresse — Abbruch."
  exit 1
fi

bluetoothctl disconnect "$MAC" 2>/dev/null || true
bluetoothctl remove "$MAC" 2>/dev/null || true

ADAPTER=$(bluetoothctl list | awk '/Controller/{print $2; exit}')
if [[ -n "${ADAPTER}" ]]; then
  CACHE="/var/lib/bluetooth/${ADAPTER}/cache/${MAC}"
  if [[ -e "${CACHE}" ]]; then
    echo "Lösche Cache: ${CACHE}"
    sudo rm -f "${CACHE}"
  fi
fi

echo "Fertig. ComModule neu einschalten, dann im Dashboard erneut Scan + Start."
