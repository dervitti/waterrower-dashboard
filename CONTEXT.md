# CONTEXT — WaterRower Dashboard

Ubiquitous language for this codebase. Prefer these terms in issues, ADRs, tests, and UI copy.

## Core devices

| Term | Meaning |
|------|---------|
| **S4** | WaterRower Series IV performance monitor (USB CDC ACM protocol). |
| **ComModule** | Official BLE accessory on the S4 mini-USB port; exposes **FTMS**. |
| **S4 Comms** | BLE advertised name of a ComModule (e.g. `S4 Comms 33`). |
| **USB path** | Laptop ↔ S4 via USB cable → `/dev/ttyACM*`. Reliable on Linux. |
| **BLE path** | Laptop ↔ ComModule via Bluetooth LE / BlueZ. Flaky on SW rev 1.30 + desktop BT. |

## Training concepts

| Term | Meaning |
|------|---------|
| **Workout** | One live session from Start until Stop (source: `usb` \| `ble` \| `demo`). |
| **Session** | Persisted workout record in SQLite (`sessions` + `samples`). |
| **User / Athlet** | Profile: name, sex, birth year, weight, optional max-HR override. |
| **HFmax** | Max heart rate — estimated from sex/age/weight, or manual override. |
| **Puls-Zone** | One of five bands as % of HFmax (Gesundheit → Wettkampf). |
| **Intensity** | Average speed from S4 memory (m/s); hero metric in the UI. |
| **Pace** | Seconds per 500 m. |
| **SPM** | Strokes per minute. |
| **BPM** | Heart rate from S4 (often via ANT+ strap → S4 → stream). |

## Software modules (code)

| Term | Meaning |
|------|---------|
| **WorkoutManager** | Orchestrates live source, timer, samples, WebSocket fan-out. |
| **UsbRowerClient** | S4 USB CDC reader (`app/ble/usb_s4.py`). |
| **BluezFtmsClient** | Linux D-Bus FTMS client (preferred BLE backend). |
| **FtmsRowerClient** | Bleak-based FTMS client (fallback). |
| **IdleInhibit** | `systemd-inhibit` while a workout is active. |

## Avoid

- Calling the ComModule “the S4” — the S4 is the monitor; ComModule is the BLE dongle.
- Treating `ttyS*` as USB — those are dead platform ports; S4 is `ttyACM*`.
- OS-level pairing of ComModule (Sway/blueman) during app BLE connect.

## Formula (HFmax estimate)

`HFmax ≈ 210 − 0.5·age − 0.05·weight_kg` (+4 for male). Override via User.max_hr.
