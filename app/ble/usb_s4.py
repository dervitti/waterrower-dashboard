"""WaterRower S4 USB (CDC ACM) client — Linux fallback.

Memory map from oarsman/S4 USB Protocol Iss 1.04 / node-waterrower:
  055 D  distance meters
  1A9 S  stroke rate (SPM)
  148 D  total/instant speed cm/s
  14A D  average speed (intensity) cm/s
  1A0 D  heart rate
  088 D  watts (oft 0 → dann aus Speed berechnet)
  08A T  calories
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable

from app.ble.parser import ParsedRowerData

logger = logging.getLogger(__name__)

MetricsCallback = Callable[[ParsedRowerData], Awaitable[None] | None]
StatusCallback = Callable[[str], Awaitable[None] | None]

# size letter → payload hex digit count
SIZE_HEX_LEN = {"S": 2, "D": 4, "T": 6}

# (address, size)
MEM_DISTANCE = ("055", "D")
MEM_STROKE_RATE = ("1A9", "S")
MEM_SPEED = ("148", "D")  # instant intensity cm/s
MEM_AVG_SPEED = ("14A", "D")  # average intensity cm/s (S4 Intensity-Fenster)
MEM_HEART_RATE = ("1A0", "D")
MEM_WATTS = ("088", "D")  # oft 0 am S4 — dann aus Speed berechnet
MEM_STROKE_COUNT = ("140", "D")
# Chronometer-Memory (1E1–1E3) ist firmware-abhängig und liefert
# oft Müll (Sekunden×3600). Zeit läuft softwareseitig (Timer-UI).

YIELD_S = 0.025  # protocol: yield ~25ms between packets
# S4-SPM im Speicher bleibt oft stehen, Display geht auf 0 —
# nach X Sekunden ohne neuen Stroke → SPM 0
SPM_IDLE_S = 3.0

# Linux list_ports liefert oft Dutzende tote /dev/ttyS* (kein USB).
_SKIP_PORT_RE = re.compile(r"/ttyS\d+$|/ttyAMA\d+$|/ttyprintk|/ttyUSB_?$")


def _is_usb_cdc_candidate(device: str) -> bool:
    """S4 hängt als CDC ACM (ttyACM*) oder selten ttyUSB*."""
    name = device.rsplit("/", 1)[-1]
    return name.startswith(("ttyACM", "ttyUSB"))


def _port_usable(device: str) -> bool:
    if _SKIP_PORT_RE.search(device):
        return False
    return True


def _watts_from_speed_cm_s(speed_cm_s: float) -> float:
    """Concept2-ähnliche Näherung: P = 2.8 · v³ (v in m/s).

    S4 speichert Watt unter 088 oft nicht; Display-Watt kommen aus Speed.
    """
    v = float(speed_cm_s) / 100.0
    if v <= 0:
        return 0.0
    return round(2.8 * (v**3), 1)


class UsbRowerClient:
    def __init__(
        self,
        on_metrics: MetricsCallback,
        on_status: StatusCallback | None = None,
        port: str | None = None,
    ) -> None:
        self._on_metrics = on_metrics
        self._on_status = on_status
        self._port_name = port
        self._stop = asyncio.Event()
        self._ser = None
        self.device_name: str | None = None
        self.connected = False
        self._t0: float | None = None
        self._last_strokes: int | None = None
        self._last_stroke_change_at: float | None = None

    async def _emit_status(self, message: str) -> None:
        logger.info("USB status: %s", message)
        if self._on_status:
            result = self._on_status(message)
            if asyncio.iscoroutine(result):
                await result

    @staticmethod
    def list_ports() -> list[str]:
        try:
            from serial.tools import list_ports
        except ImportError as exc:
            raise RuntimeError("pyserial fehlt — pip install pyserial") from exc
        ports: list[str] = []
        for p in list_ports.comports():
            if not _port_usable(p.device):
                logger.debug("serial skip junk: %s (%s)", p.device, p.description)
                continue
            ports.append(p.device)
            logger.info(
                "serial port: %s (%s) [%s]",
                p.device,
                p.description or "n/a",
                "usb-cdc" if _is_usb_cdc_candidate(p.device) else "other",
            )
        # ACM/USB zuerst
        ports.sort(key=lambda d: (0 if _is_usb_cdc_candidate(d) else 1, d))
        return ports

    @staticmethod
    def probe_port(port: str) -> bool:
        """Kurz prüfen, ob am Port ein S4 antwortet (_WR_ / PING)."""
        if not _port_usable(port):
            return False
        try:
            import serial
            from serial import SerialException
        except ImportError:
            return False
        ser = None
        try:
            ser = serial.Serial(port=port, baudrate=115200, timeout=0.25)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(b"USB\r\n")
            ser.flush()
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="ignore").strip()
                if "_WR_" in line or line.startswith("PING") or line.startswith("IV"):
                    return True
            return False
        except (OSError, SerialException) as exc:
            logger.debug("probe %s: %s", port, exc)
            return False
        except Exception:  # noqa: BLE001
            return False
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass

    @classmethod
    def find_s4_port(cls) -> str | None:
        """Ersten Port mit S4-Antwort finden (nur USB-CDC-Kandidaten)."""
        import os

        env = os.environ.get("WR_USB_PORT", "").strip()
        if env:
            if cls.probe_port(env):
                return env
            logger.warning("WR_USB_PORT=%s antwortet nicht wie S4", env)
            # trotzdem zurückgeben wenn gesetzt — User weiß Bescheid
            if _port_usable(env):
                return env
            return None
        try:
            ports = cls.list_ports()
        except Exception:  # noqa: BLE001
            return None
        usb_ports = [p for p in ports if _is_usb_cdc_candidate(p)]
        for port in usb_ports:
            if cls.probe_port(port):
                return port
        return None

    def _pick_port(self) -> str:
        import os

        if self._port_name:
            if not _port_usable(self._port_name):
                raise RuntimeError(
                    f"Port {self._port_name} ist kein USB-CDC (ttyS* sind tot). "
                    "S4 per USB-Kabel → /dev/ttyACM0. Env: WR_USB_PORT=/dev/ttyACM0"
                )
            return self._port_name
        found = self.find_s4_port()
        if found:
            return found
        ports = [p for p in self.list_ports() if _is_usb_cdc_candidate(p)]
        if ports:
            return ports[0]
        env = os.environ.get("WR_USB_PORT", "").strip()
        hint = f" Oder WR_USB_PORT={env} prüfen." if env else ""
        raise RuntimeError(
            "Kein S4-USB-Port (/dev/ttyACM*). "
            "ComModule ist BLE — für USB das S4-Monitor-Kabel direkt an den PC. "
            "Kabel stecken, dann: ls -l /dev/ttyACM* ; "
            "sudo usermod -aG dialout $USER && neu anmelden."
            + hint
        )

    def _write(self, cmd: str) -> None:
        assert self._ser is not None
        self._ser.write((cmd.strip() + "\r\n").encode("ascii", errors="ignore"))
        self._ser.flush()
        time.sleep(YIELD_S)

    def _read_line(self, timeout: float = 0.35) -> str | None:
        assert self._ser is not None
        self._ser.timeout = timeout
        raw = self._ser.readline()
        if not raw:
            return None
        return raw.decode("ascii", errors="ignore").strip()

    def _drain(self) -> None:
        assert self._ser is not None
        try:
            self._ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass

    def _read_mem(self, addr: str, size: str) -> int | None:
        """Read memory; parse only the exact hex width for S/D/T."""
        hex_len = SIZE_HEX_LEN[size]
        self._write(f"IR{size}{addr}")
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline:
            line = self._read_line(0.12)
            if not line:
                continue
            if line.startswith(("PING", "ERROR", "OK", "SS", "SE")) or line.startswith("P"):
                # Pxx pulse train — ignore
                if re.match(r"^P[0-9A-Fa-f]{2}$", line):
                    continue
                if line.startswith(("PING", "ERROR", "OK", "SS", "SE")):
                    continue
            # ID + size + addr + payload
            m = re.match(rf"^ID([SDT]){addr}([0-9A-Fa-f]+)$", line)
            if not m:
                logger.debug("USB skip: %s", line)
                continue
            payload = m.group(2)
            if len(payload) < hex_len:
                continue
            # Exactly the declared width (ignore trailing garbage)
            payload = payload[:hex_len]
            try:
                return int(payload, 16)
            except ValueError:
                return None
        return None

    async def connect(self) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial fehlt: pip install pyserial") from exc

        port = await asyncio.to_thread(self._pick_port)
        await self._emit_status(f"Öffne {port} @ 115200…")

        def _open():
            import serial
            from serial import SerialException

            try:
                ser = serial.Serial(port=port, baudrate=115200, timeout=0.3)
            except (OSError, SerialException) as exc:
                raise RuntimeError(
                    f"Kann {port} nicht öffnen: {exc}. "
                    "S4-USB-Kabel? ls -l /dev/ttyACM* ; Gruppe dialout?"
                ) from exc
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            return ser

        self._ser = await asyncio.to_thread(_open)
        self.device_name = f"S4 USB ({port})"
        await asyncio.to_thread(self._drain)
        await asyncio.to_thread(self._write, "USB")
        hello = None
        for _ in range(25):
            line = await asyncio.to_thread(self._read_line, 0.2)
            if not line:
                continue
            if "_WR_" in line or line.startswith("IV"):
                hello = line
                break
            if line.startswith("PING"):
                hello = line
                break
        if hello:
            await self._emit_status(f"S4: {hello}")
            if hello.startswith("_WR_"):
                await asyncio.to_thread(self._write, "IV?")
                ver = await asyncio.to_thread(self._read_line, 0.4)
                if ver:
                    await self._emit_status(f"Firmware: {ver}")
        else:
            await self._emit_status("Kein _WR_ — polling trotzdem")

        self.connected = True
        self._t0 = time.monotonic()
        self._last_strokes = None
        self._last_stroke_change_at = None
        self._stop.clear()

    def _poll_once(self) -> ParsedRowerData:
        distance = self._read_mem(*MEM_DISTANCE)
        spm = self._read_mem(*MEM_STROKE_RATE)
        speed = self._read_mem(*MEM_SPEED)
        avg_speed = self._read_mem(*MEM_AVG_SPEED)
        hr = self._read_mem(*MEM_HEART_RATE)
        watts = self._read_mem(*MEM_WATTS)
        strokes = self._read_mem(*MEM_STROKE_COUNT)

        now = time.monotonic()
        if strokes is not None:
            if self._last_strokes is None or strokes != self._last_strokes:
                self._last_strokes = int(strokes)
                self._last_stroke_change_at = now

        # Pace kommt im WorkoutManager aus Zeit/Distanz (stabiler als Momentan-Speed)

        # S4 Average Intensity: cm/s → m/s
        avg_intensity_mps = None
        if avg_speed is not None and 0 <= avg_speed < 1000:
            avg_intensity_mps = round(float(avg_speed) / 100.0, 2)

        stroke_rate = None
        if spm is not None and 0 <= spm < 80:
            stroke_rate = float(spm)
        # Pause: kein neuer Stroke seit SPM_IDLE_S (S4-SPM bleibt oft im Speicher stehen)
        if (
            self._last_stroke_change_at is not None
            and (now - self._last_stroke_change_at) >= SPM_IDLE_S
        ):
            stroke_rate = 0.0

        hr_val = None
        if hr is not None:
            # D-read may include high byte; BPM is low byte / full if plausible
            hr_val = int(hr) & 0xFF
            if hr_val == 0 or hr_val > 230:
                hr_val = int(hr) if 30 <= int(hr) <= 230 else None

        # Watt: Speicher 088 falls gesetzt, sonst aus Speed (cm/s)
        power_w = None
        if watts is not None and watts > 0:
            power_w = float(watts)
        elif speed is not None and speed > 0:
            power_w = _watts_from_speed_cm_s(speed)
        elif stroke_rate == 0.0:
            power_w = 0.0

        return ParsedRowerData(
            distance_m=float(distance) if distance is not None else None,
            stroke_count=strokes,
            stroke_rate=stroke_rate,
            heart_rate=hr_val,
            power_w=power_w,
            pace_s=None,
            avg_intensity_mps=avg_intensity_mps,
            # Zeit steuert der Workout-Timer (Start/Pause/Reset), nicht USB
            elapsed_s=None,
        )

    async def run(self) -> None:
        if not self.connected:
            await self.connect()
        await self._emit_status("USB Live-Polling…")
        while not self._stop.is_set():
            try:
                metrics = await asyncio.to_thread(self._poll_once)
                result = self._on_metrics(metrics)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                logger.exception("USB poll error")
                await self._emit_status("USB Lesefehler")
                await asyncio.sleep(1.0)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.05)
            except asyncio.TimeoutError:
                pass
        self.connected = False
        await self._emit_status("USB gestoppt")

    async def stop(self) -> None:
        self._stop.set()
        ser = self._ser
        self._ser = None
        self.connected = False
        if ser is not None:
            try:
                await asyncio.to_thread(ser.close)
            except Exception:  # noqa: BLE001
                pass


def find_default_port() -> str | None:
    return UsbRowerClient.find_s4_port()
