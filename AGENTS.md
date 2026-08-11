# WaterRower Dashboard — Agent notes

Python FastAPI live dashboard for WaterRower **S4** (USB CDC) and **ComModule** (BLE FTMS).

## Agent skills

### Issue tracker

GitHub Issues on `dervitti/waterrower-dashboard` via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default mattpocock vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Run (Linux)

```bash
./start.sh          # venv + uvicorn :8000 + browser
# or
./run.sh
```

Env: `WR_USB_PORT`, `WR_BLE_ADAPTER`, `WR_BLE_BACKEND=dbus|bleak`.
