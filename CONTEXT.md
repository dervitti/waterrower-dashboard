# CONTEXT — WaterRower Dashboard

Ubiquitous language for this codebase. Prefer these terms in issues, ADRs, tests, and UI copy.

## Core devices

| Term | Meaning |
|------|---------|
| **S4** | WaterRower Series IV performance monitor (USB CDC ACM protocol). |
| **ComModule** | Official BLE accessory on the S4 mini-USB port; exposes **FTMS**. |
| **S4 Comms** | BLE advertised name of a ComModule (e.g. `S4 Comms 33`). |
| **USB path** | Laptop ↔ S4 via USB cable → `/dev/ttyACM*`. **Default / production** on Linux. |
| **BLE path** | Laptop ↔ ComModule via Bluetooth LE / BlueZ. **Unsupported for production** with ComModule SW rev **1.30** on desktop Linux (phone apps may still work). Experimental only. |

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
| **BPM** | Heart rate from S4 memory over USB (ANT+ strap → S4 → USB). FTMS/ComModule often omits HR. |

## Software modules (code)

| Term | Meaning |
|------|---------|
| **WorkoutManager** | Orchestrates live source, timer, samples, WebSocket fan-out. |
| **UsbRowerClient** | S4 USB CDC reader (`app/ble/usb_s4.py`) — primary live source. |
| **BluezFtmsClient** | Linux D-Bus FTMS client (experimental BLE backend). |
| **FtmsRowerClient** | Bleak-based FTMS client (fallback). |
| **IdleInhibit** | While workout active: `systemd-inhibit`, pause `swayidle`/`hypridle`, optional ScreenSaver/portal inhibit; UI also holds Screen Wake Lock. |

## Avoid

- Calling the ComModule “the S4” — the S4 is the monitor; ComModule is the BLE dongle.
- Treating `ttyS*` as USB — those are dead platform ports; S4 is `ttyACM*`.
- OS-level pairing of ComModule (Sway/blueman) during app BLE connect.
- Documenting private machine paths (Nextcloud sync dirs, `$HOME/…` clones) in the repo — use `git clone` + `scripts/install-launcher.sh` (bakes local root at install time).
- Recommending desktop BLE with SW rev 1.30 as a supported training path.

## Formula (HFmax estimate)

`HFmax ≈ 210 − 0.5·age − 0.05·weight_kg` (+4 for male). Override via User.max_hr.
