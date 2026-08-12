# WaterRower Dashboard

Live-Dashboard für WaterRower **S4** (USB) mit User-Verwaltung und Session-Speicherung. ComModule/BLE nur experimentell.

**Repo:** [github.com/dervitti/waterrower-dashboard](https://github.com/dervitti/waterrower-dashboard)

## Was es macht

- **Primär:** Verbindet sich per **USB** mit dem S4-Monitor (`/dev/ttyACM*`)
- Zeigt Live-Metriken: Intensität, Pace, SPM, Distanz, Zeit, kcal, Strokes, **Herzfrequenz** (vom S4, wenn Gurt am Monitor hängt)
- Mehrere User anlegen und Sessions speichern (SQLite)
- **Demo-Modus** zum Testen ohne Hardware
- **Optional / experimentell:** Bluetooth LE / FTMS über ComModule (unter Linux mit alter Firmware nicht für den Alltag geeignet — siehe unten)

## Verbindung

| Pfad | Status |
|------|--------|
| **USB** (Laptop ↔ S4) | **Standard** — zuverlässig unter Linux |
| **Demo** | Ohne Hardware |
| **BLE** (ComModule) | Experimentell — siehe Warnung |

### Bluetooth / ComModule (nicht für Produktion)

Desktop-Bluetooth mit ComModule **SW Rev 1.30** funktioniert unter Linux **nicht zuverlässig** und wird **nicht unterstützt**. Handy-Apps können trotzdem gehen.

Empfehlung: **USB-Kabel am S4**, ComModule nicht über die System-Bluetooth-UI koppeln.

## Puls

Der ANT+-Brustgurt spricht mit dem **S4-Monitor** (ANT-Empfänger / HR-Kit), nicht direkt mit dem Laptop.

Voraussetzung:

1. ANT-Empfänger am S4 ist installiert und der Gurt ist mit dem Monitor synchron
2. Am S4 wird die Herzfrequenz angezeigt
3. Über **USB** liest das Dashboard die HF aus dem S4-Speicher mit

Wenn am S4 Puls sichtbar ist, im Dashboard aber `—` bei BPM: Firmware/Speicheradresse oder Gurt-Sync prüfen. (Über BLE/FTMS leitet das ComModule die HF oft gar nicht weiter.)

## Starten

Voraussetzung: **Python 3.10+** (`python3 --version` prüfen).

```bash
git clone https://github.com/dervitti/waterrower-dashboard.git
cd waterrower-dashboard
bash setup.sh                  # einmalig: venv + pip
./start.sh                     # venv + Server + Browser
```

Browser: [http://127.0.0.1:8000](http://127.0.0.1:8000)

**dmenu / Anwendungsmenü** (einmalig, aus dem Repo-Verzeichnis):

```bash
bash scripts/install-launcher.sh
```

Das Skript schreibt den **aktuellen Repo-Pfad** in `~/.local/bin/waterrower` und den Desktop-Eintrag — keine festen Sync-/Home-Pfade im Repo. Danach in dmenu: `waterrower` bzw. „WaterRower Dashboard“.

Nur Server (ohne Browser): `./run.sh`

Oder manuell:

```bash
python3 --version              # muss >= 3.10 sein
sudo apt install python3-venv python3-pip   # falls nötig
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Wenn `python3` zu alt ist (z.B. 3.8/3.9):

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Wichtig: `uvicorn` kommt aus der venv — immer zuerst `source .venv/bin/activate`, oder `./run.sh` / `./start.sh` nutzen.

Optional: Port/USB-Gerät per Env — `WR_PORT`, `WR_USB_PORT=/dev/ttyACM0`.

## Nutzung

1. User anlegen und auswählen
2. S4 per USB verbinden (Gerät sollte als `/dev/ttyACM*` erscheinen)
3. **USB** starten (oder **Demo** ohne Hardware)
4. Nach dem Rudern **Stop** — Session wird gespeichert

### Optional / experimentell (BLE)

Nur wenn du bewusst am ComModule experimentierst (neuere Firmware, kein Alltagspfad):

1. Bluetooth-Dienst aktiv (`bluetoothctl power on`)
2. User in Gruppe `bluetooth` (oder udev/polkit)
3. ComModule einschalten; **nicht** über Sway/Blueman fest koppeln
4. Im UI **Scan** → **Start**

Siehe auch `docs/adr/0001-prefer-usb-on-linux.md` und `scripts/ble_probe.py`.
