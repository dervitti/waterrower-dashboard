# WaterRower Dashboard

Live-Dashboard für WaterRower **S4 + ComModule** mit User-Verwaltung und Session-Speicherung.

**Repo:** [github.com/dervitti/waterrower-dashboard](https://github.com/dervitti/waterrower-dashboard)

## Was es macht

- Verbindet sich per **Bluetooth LE / FTMS** mit dem WaterRower ComModule
- Zeigt Live-Metriken: Pace, SPM, Watt, Distanz, Zeit, kcal, Strokes, **Herzfrequenz** (falls im FTMS-Stream enthalten)
- Mehrere User anlegen und Sessions speichern (SQLite)
- **Demo-Modus** zum Testen ohne Hardware

## Puls über ComModule

Der ANT+-Brustgurt spricht mit dem **S4-Monitor** (über den ANT-Empfänger im Monitor / HR-Kit), nicht direkt mit dem Laptop.

Voraussetzung:

1. ANT-Empfänger am S4 ist installiert und der Gurt ist mit dem Monitor synchron
2. Am S4 wird die Herzfrequenz angezeigt
3. Das ComModule leitet die Daten per FTMS weiter — die HF steckt dann im Feld *Heart Rate* der Rower-Data-Characteristic

Wenn am S4 Puls sichtbar ist, im Dashboard aber `—` bei BPM: das ComModule sendet die HF in deiner Firmware möglicherweise nicht. Dann später optional ein BT-Pulsgurt oder ANT+-USB-Stick.

## Starten

Voraussetzung: **Python 3.10+** (`python3 --version` prüfen).

Windows (dieser PC / Nextcloud-Sync):
`C:\Users\Sebastian\Oktasilan-NextCloud\Rower`

Linux-Laptop (Nextcloud-Client):
`~/NextcloudOktasilan/Rower` bzw. dein Sync-Pfad

### Linux (empfohlen)

```bash
cd ~/NectcloudOktasilan/Rower   # dein Sync-Pfad
bash setup.sh                  # einmalig: venv + pip
./start.sh                     # venv + Server + Browser
```

**dmenu / Anwendungsmenü** (einmalig):

```bash
bash scripts/install-launcher.sh
```

Danach in dmenu: `waterrower` bzw. „WaterRower Dashboard“.

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

Wichtig: `uvicorn` kommt aus der venv — immer zuerst `source .venv/bin/activate`, oder `./run.sh` nutzen.


Browser: [http://127.0.0.1:8000](http://127.0.0.1:8000)

### Bluetooth unter Linux

- Bluetooth-Dienst aktiv (`bluetoothctl power on`)
- User in der Gruppe `bluetooth` (oder entsprechendes udev/polkit)
- ComModule einschalten, bis LED langsam blinkt; am S4 sollte **PC** stehen

## Nutzung

1. User anlegen und auswählen
2. Optional **Scan** für das ComModule
3. **Start** (echtes Gerät) oder **Demo**
4. Nach dem Rudern **Stop** — Session wird gespeichert
