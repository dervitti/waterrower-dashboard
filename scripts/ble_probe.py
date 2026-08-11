#!/usr/bin/env python3
"""Diagnose S4 Comms BLE — BlueZ D-Bus FTMS.

Vor dem Lauf (wichtig bei Sway-Popups „S4 Comms getrennt“):
  - Handy-BLE zum ComModule aus
  - In Sway/blueman: Gerät entfernen oder Auto-Connect aus
  - Internen Adapter aus:
      busctl set-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered b false

Usage:
  WR_BLE_ADAPTER=hci1 python scripts/ble_probe.py 80:1F:12:B1:34:21
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.ble.bluez_ftms import BluezFtmsClient, resolve_ble_adapter  # noqa: E402
from app.ble.bluez_util import controller_mac, list_hci_adapters  # noqa: E402
from app.ble.parser import ParsedRowerData  # noqa: E402


def _probe_version() -> str:
    try:
        from app.version import VERSION

        return VERSION
    except Exception as exc:  # noqa: BLE001
        return f"? ({exc})"


async def main() -> None:
    address = sys.argv[1] if len(sys.argv) > 1 else None
    version = _probe_version()
    print(f"=== WaterRower ble_probe v{version} ===")
    adapter = resolve_ble_adapter()
    adapters = list_hci_adapters()
    ctrl = controller_mac(adapter) if adapter else None
    print(
        f"=== Adapter: {adapter or 'default'} MAC={ctrl or '?'} "
        f"(verfügbar: {', '.join(adapters) or '—'}) ==="
    )
    print(
        "Wenn Sway ständig „S4 Comms getrennt“ zeigt: Desktop-BT für dieses Gerät\n"
        "entfernen, Phone aus, dann:\n"
        "  busctl set-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered b false\n"
        "  WR_BLE_ADAPTER=hci1 python scripts/ble_probe.py …"
    )
    if not adapter:
        print("FAIL: kein Adapter.")
        return

    packets = 0
    last_print = 0.0

    async def on_metrics(m: ParsedRowerData) -> None:
        nonlocal packets, last_print
        packets += 1
        now = time.monotonic()
        if packets <= 12 or packets % 10 == 0 or now - last_print > 2.0:
            last_print = now
            print(
                f"  #{packets} spm={m.stroke_rate} dist={m.distance_m} "
                f"pace={m.pace_s} hr={m.heart_rate} watts={m.power_w}"
            )

    async def on_status(msg: str) -> None:
        print(f"  status: {msg}")

    client = BluezFtmsClient(on_metrics, on_status)
    try:
        await client.connect(address=address, timeout=40.0)
        print("\n=== Notify aktiv — bitte 15s rudern ===")
        try:
            await asyncio.wait_for(client.run_until_stopped(), timeout=15.0)
            print(f"FAIL: Link weg früh (packets={packets})")
        except asyncio.TimeoutError:
            print(f"OK: stabil mit Notify, packets={packets}")
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAIL: {exc}")
        raise SystemExit(1) from exc
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
