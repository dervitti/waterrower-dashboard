# ADR-0001: Prefer USB for live training on Linux

## Status

Accepted

## Context

The ComModule (BLE FTMS) with software revision 1.30 drops links under BlueZ when the desktop Bluetooth stack also manages the device. Phone apps work; Linux system-level connect often yields `ServicesResolved` without GATT characteristics, then disconnect.

USB CDC to the S4 monitor enumerates as `/dev/ttyACM*` and streams the memory map reliably.

## Decision

- Default production path on Linux: **USB** (`UsbRowerClient`).
- BLE remains available (`BluezFtmsClient` / Bleak) for experimentation; document ComModule firmware and “no desktop BT ownership” constraints.
- Auto-connect on page load probes USB first (`/api/workout/usb-status`).

## Consequences

Dashboard UX emphasizes the USB button; BLE troubleshooting stays in `scripts/ble_probe.py` and env vars (`WR_BLE_ADAPTER`, `WR_BLE_BACKEND`).
