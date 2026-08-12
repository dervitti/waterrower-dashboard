# ADR-0001: Prefer USB for live training on Linux

## Status

Accepted

## Context

The ComModule (BLE FTMS) with software revision **1.30** does not work reliably under desktop BlueZ: links drop when the system Bluetooth stack also manages the device; connect often yields `ServicesResolved` without GATT characteristics, then disconnect. **Desktop BLE with SW 1.30 is unsupported for production.** Phone apps may still work.

USB CDC to the S4 monitor enumerates as `/dev/ttyACM*` and streams the memory map (including heart rate when the strap is paired to the S4) reliably.

## Decision

- **Default / production path on Linux: USB** (`UsbRowerClient`).
- BLE remains in the codebase (`BluezFtmsClient` / Bleak) for **experimentation only**; do not present it as a supported daily path while on SW 1.30.
- Auto-connect on page load probes USB first (`/api/workout/usb-status`).
- Public docs use `git clone` of the GitHub repo; launchers bake the local repo path via `scripts/install-launcher.sh` — no private sync paths in the repository.

## Consequences

- README and UI emphasize the **USB** button; BLE is documented as optional/experimental with an explicit 1.30 warning.
- BLE troubleshooting stays in `scripts/ble_probe.py` and env vars (`WR_BLE_ADAPTER`, `WR_BLE_BACKEND`).
- Prefer upgrading ComModule firmware (e.g. 4.x) before investing further in desktop BLE.
