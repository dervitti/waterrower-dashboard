# WaterRower Dashboard — Agent notes

Python FastAPI live dashboard for WaterRower **S4** (**USB CDC** primary) and optional **ComModule** (BLE FTMS, experimental).

See `CONTEXT.md` and `docs/adr/0001-prefer-usb-on-linux.md`: desktop BLE with ComModule SW **1.30** is **unsupported**; prefer USB.

## Agent skills

### Issue tracker

GitHub Issues on `dervitti/waterrower-dashboard` via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default mattpocock vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Run (Linux)

```bash
git clone https://github.com/dervitti/waterrower-dashboard.git
cd waterrower-dashboard
bash setup.sh
./start.sh          # venv + uvicorn :8000 + browser
# or
./run.sh
bash scripts/install-launcher.sh   # optional: dmenu/desktop; bakes this clone's path
```

Env: `WR_USB_PORT`, `WR_PORT`, `WR_BLE_ADAPTER`, `WR_BLE_BACKEND=dbus|bleak`.
