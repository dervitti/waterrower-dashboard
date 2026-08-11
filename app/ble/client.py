"""BLE FTMS client for WaterRower ComModule."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from app.ble.bluez_util import (
    controller_mac,
    disconnect_device,
    list_hci_adapters,
    wait_services_resolved,
)
from app.ble.parser import ParsedRowerData, parse_rower_data
from app.config import FTMS_SERVICE_UUID, ROWER_DATA_UUID

logger = logging.getLogger(__name__)

HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

MetricsCallback = Callable[[ParsedRowerData], Awaitable[None] | None]
StatusCallback = Callable[[str], Awaitable[None] | None]


def resolve_ble_adapter() -> str | None:
    """HCI-Adapter wählen: WR_BLE_ADAPTER oder bei mehreren Adaptern den USB-Dongle (nicht hci0)."""
    env = os.environ.get("WR_BLE_ADAPTER", "").strip()
    if env:
        return env
    adapters = list_hci_adapters()
    if not adapters:
        return None
    if len(adapters) == 1:
        return adapters[0]
    # Intern oft hci0, USB-Dongle oft hci1+
    for name in reversed(adapters):
        if name != "hci0":
            return name
    return adapters[-1]


class FtmsRowerClient:
    def __init__(
        self,
        on_metrics: MetricsCallback,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._on_metrics = on_metrics
        self._on_status = on_status
        self._client: BleakClient | None = None
        self._device_name: str | None = None
        self._address: str | None = None
        self._adapter: str | None = resolve_ble_adapter()
        self._stop = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._char_uuids: set[str] = set()
        self._rower_uuid: str | None = None
        self._user_stop = False

    @property
    def device_name(self) -> str | None:
        return self._device_name

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    def _bluez_kwargs(self) -> dict[str, Any]:
        if self._adapter:
            return {"adapter": self._adapter}
        return {}

    async def _emit_status(self, message: str) -> None:
        logger.info("FTMS status: %s", message)
        if self._on_status:
            result = self._on_status(message)
            if asyncio.iscoroutine(result):
                await result

    def _schedule(self, coro: Awaitable[Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:  # noqa: BLE001
            logger.exception("schedule failed")

    async def scan(self, timeout: float = 8.0) -> list[dict[str, Any]]:
        self._adapter = resolve_ble_adapter()
        found: dict[str, dict[str, Any]] = {}

        def _detection(device: BLEDevice, adv: AdvertisementData) -> None:
            uuids = {u.lower() for u in (adv.service_uuids or [])}
            name = device.name or adv.local_name
            looks_ftms = FTMS_SERVICE_UUID.lower() in uuids
            looks_wr = bool(
                name
                and any(k in name.lower() for k in ("water", "comm", "wr", "s4", "rower"))
            )
            if not (looks_ftms or looks_wr):
                return
            found[device.address] = {
                "name": name,
                "address": device.address,
                "rssi": adv.rssi,
            }

        scanner = BleakScanner(detection_callback=_detection, bluez=self._bluez_kwargs())
        await scanner.start()
        try:
            await asyncio.sleep(timeout)
        finally:
            await scanner.stop()

        return sorted(found.values(), key=lambda d: d.get("rssi") or -999, reverse=True)

    def _collect_chars(self) -> bool:
        self._char_uuids.clear()
        if not self._client:
            return False
        try:
            services = self._client.services
        except BleakError:
            return False
        for service in services:
            for char in service.characteristics:
                self._char_uuids.add(char.uuid.lower())
                logger.info(
                    "GATT %s / %s props=%s",
                    service.uuid,
                    char.uuid,
                    ",".join(char.properties),
                )
        return bool(self._char_uuids)

    def _resolve_uuid(self, preferred: str) -> str | None:
        pref = preferred.lower()
        if pref in self._char_uuids:
            return preferred
        needle = pref[4:8] if pref.startswith("0000") and len(pref) >= 8 else pref[:8]
        for uuid in self._char_uuids:
            if needle in uuid.replace("-", ""):
                return uuid
        return None

    def _notification_handler(self, _sender: Any, data: bytearray) -> None:
        try:
            parsed = parse_rower_data(data)
            result = self._on_metrics(parsed)
            if asyncio.iscoroutine(result):
                self._schedule(result)
        except Exception:  # noqa: BLE001
            logger.exception("Rower-Data parse/handler failed: %s", data.hex())

    def _hr_handler(self, _sender: Any, data: bytearray) -> None:
        try:
            if not data:
                return
            flags = data[0]
            hr = data[1] if (flags & 0x01) == 0 else int.from_bytes(data[1:3], "little")
            parsed = ParsedRowerData(heart_rate=hr)
            result = self._on_metrics(parsed)
            if asyncio.iscoroutine(result):
                self._schedule(result)
        except Exception:  # noqa: BLE001
            logger.exception("HR parse failed: %s", data.hex())

    def _on_disconnect(self, _client: BleakClient) -> None:
        logger.warning("BLE disconnected by peer or stack")
        self._disconnected.set()
        self._schedule(self._emit_status("Bluetooth getrennt (Gerät oder BlueZ)"))
        if not self._user_stop:
            self._stop.set()

    async def _find_device(self, address: str | None, timeout: float) -> BLEDevice:
        bluez = self._bluez_kwargs()
        if address:
            await self._emit_status(
                f"Suche {address}" + (f" auf {self._adapter}" if self._adapter else "") + "…"
            )
            device = await BleakScanner.find_device_by_address(
                address, timeout=timeout, bluez=bluez
            )
            if device is None:
                raise RuntimeError(f"Gerät {address} nicht in Reichweite.")
            return device

        await self._emit_status(
            "Suche ComModule (FTMS)"
            + (f" auf {self._adapter}" if self._adapter else "")
            + "…"
        )
        results = await self.scan(timeout=min(timeout, 10.0))
        if not results:
            raise RuntimeError(
                "Kein FTMS/ComModule gefunden. ComModule einschalten und PC-Symbol am S4 prüfen."
            )
        device = await BleakScanner.find_device_by_address(
            results[0]["address"], timeout=timeout, bluez=bluez
        )
        if device is None:
            raise RuntimeError("Gerät nicht gefunden.")
        return device

    async def _wait_btctl_services_resolved(self, address: str, seconds: float = 20.0) -> bool:
        """Prime GATT via BlueZ D-Bus auf hciN until ServicesResolved=yes."""
        if not self._adapter:
            await self._emit_status("Kein BLE-Adapter — ServicesResolved übersprungen")
            return False

        ctrl = controller_mac(self._adapter)
        await self._emit_status(
            f"BT-Adapter {self._adapter}" + (f" ({ctrl})" if ctrl else " via D-Bus")
        )

        def _status(msg: str) -> None:
            logger.info("bluez: %s", msg)
            self._schedule(self._emit_status(msg))

        flags = await asyncio.to_thread(
            wait_services_resolved,
            self._adapter,
            address,
            scan_seconds=5.0,
            wait_seconds=seconds,
            log=_status,
        )
        if flags.get("ServicesResolved") == "yes":
            await self._emit_status("BlueZ ServicesResolved=yes")
            return True
        if flags.get("Connected") == "no":
            await self._emit_status("bluetoothctl/D-Bus: Link weg vor ServicesResolved")
            return False
        await self._emit_status(f"Timeout: ServicesResolved nicht erreicht ({flags})")
        return False

    async def _bleak_attach_and_notify(
        self, device: BLEDevice, timeout: float, *, pair: bool
    ) -> None:
        """Bleak connect + GATT + Notify. Bleak muss Connect selbst machen (GATT sehen)."""
        self._client = BleakClient(
            device,
            disconnected_callback=self._on_disconnect,
            timeout=max(timeout, 40.0),
            pair=pair,
            bluez=self._bluez_kwargs(),
        )
        await self._emit_status(
            f"[1/3] Bleak connect auf {self._adapter or 'default'} "
            f"({'mit' if pair else 'ohne'} Pairing)…"
        )
        await self._client.connect()
        if self._disconnected.is_set() or not self._client.is_connected:
            raise RuntimeError("Disconnect direkt nach Connect.")

        await self._emit_status("[2/3] Warte auf GATT Services…")
        services_ok = False
        for i in range(60):
            if self._disconnected.is_set() or not self._client.is_connected:
                raise RuntimeError(
                    f"Disconnect während Service Discovery (nach ~{i * 0.25:.1f}s). "
                    f"Probe: WR_BLE_ADAPTER={self._adapter or ''} "
                    f"python scripts/ble_probe.py {device.address}"
                )
            if self._collect_chars():
                services_ok = True
                break
            await asyncio.sleep(0.25)

        if not services_ok:
            raise RuntimeError(
                "GATT-Services leer/timeout. "
                f"bluetoothctl remove {device.address}, Cache löschen, Probe erneut."
            )

        rower_uuid = self._resolve_uuid(ROWER_DATA_UUID)
        hr_uuid = self._resolve_uuid(HR_MEASUREMENT_UUID)
        self._rower_uuid = rower_uuid

        await self._emit_status("[3/3] Notifications…")
        if rower_uuid:
            await self._client.start_notify(rower_uuid, self._notification_handler)
        if hr_uuid:
            try:
                await self._client.start_notify(hr_uuid, self._hr_handler)
                await self._emit_status("HR-Service (0x180D) aktiv")
            except BleakError as exc:
                logger.info("HR notify optional: %s", exc)

        if not rower_uuid and not hr_uuid:
            raise RuntimeError(
                "Weder Rower-Data (2AD1) noch HR (2A37) gefunden. "
                f"Chars: {sorted(self._char_uuids)}"
            )

        await asyncio.sleep(1.0)
        if self._disconnected.is_set() or not self._client.is_connected:
            raise RuntimeError("Disconnect nach Notify.")

    async def _connect_once(self, device: BLEDevice, timeout: float) -> None:
        self._device_name = device.name or device.address
        self._address = device.address
        self._disconnected.clear()
        self._adapter = resolve_ble_adapter()

        prefer_pair = os.environ.get("WR_BLE_PAIR", "0").strip() in {"1", "true", "yes"}

        # 1) Bleak allein — Manager sieht InterfaceAdded während Connect/Discovery
        try:
            await self._bleak_attach_and_notify(device, timeout, pair=prefer_pair)
        except Exception as first_exc:  # noqa: BLE001
            logger.info("Direkter Bleak-Connect fehlgeschlagen: %s", first_exc)
            await self._safe_disconnect()
            if self._adapter:
                await asyncio.to_thread(disconnect_device, self._adapter, device.address)
            await asyncio.sleep(0.4)

            # 2) D-Bus-Prime beweist den Link, dann Disconnect, dann Bleak neu
            await self._emit_status("Fallback: D-Bus prime → disconnect → Bleak…")
            primed = await self._wait_btctl_services_resolved(device.address, seconds=20.0)
            if self._adapter:
                await asyncio.to_thread(disconnect_device, self._adapter, device.address)
            await asyncio.sleep(0.8)
            if not primed:
                await self._emit_status("D-Bus-Prime ohne ServicesResolved — Bleak trotzdem…")

            self._disconnected.clear()
            device = await self._find_device(device.address, min(timeout, 12.0))
            await self._bleak_attach_and_notify(device, timeout, pair=False)

        self._stop.clear()
        self._disconnected.clear()
        await self._emit_status(
            f"Verbunden mit {self._device_name} via {self._adapter or 'default'} — Link stabil"
        )

    async def connect(self, address: str | None = None, timeout: float = 40.0) -> None:
        self._loop = asyncio.get_running_loop()
        self._user_stop = False
        self._stop.clear()
        self._disconnected.clear()
        self._adapter = resolve_ble_adapter()
        adapters = list_hci_adapters()
        await self._emit_status(
            f"Adapter: {self._adapter or 'default'} (verfügbar: {', '.join(adapters) or '—'})"
        )

        device = await self._find_device(address, timeout)
        last_error: Exception | None = None
        attempts = int(os.environ.get("WR_BLE_RETRIES", "4"))

        for attempt in range(1, attempts + 1):
            try:
                await self._emit_status(f"Versuch {attempt}/{attempts}…")
                await self._connect_once(device, timeout)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("Connect attempt %s failed: %s", attempt, exc)
                await self._safe_disconnect()
                if attempt < attempts:
                    await self._emit_status(f"Versuch {attempt} fehlgeschlagen: {exc}")
                    await asyncio.sleep(2.0)
                    try:
                        device = await self._find_device(address or self._address, timeout)
                    except Exception:  # noqa: BLE001
                        pass

        raise RuntimeError(str(last_error) if last_error else "BLE-Verbindung fehlgeschlagen")

    async def _safe_disconnect(self) -> None:
        client = self._client
        self._client = None
        if not client:
            return
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    async def run_until_stopped(self) -> None:
        reconnects = int(os.environ.get("WR_BLE_LIVE_RECONNECTS", "8"))
        while True:
            wait_stop = asyncio.create_task(self._stop.wait())
            wait_disc = asyncio.create_task(self._disconnected.wait())
            _done, pending = await asyncio.wait(
                {wait_stop, wait_disc},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if self._user_stop:
                return

            if self._disconnected.is_set() and reconnects > 0 and not self._user_stop:
                reconnects -= 1
                await self._emit_status(f"Link weg — Reconnect ({reconnects} übrig)…")
                await self._safe_disconnect()
                await asyncio.sleep(1.2)
                try:
                    device = await self._find_device(self._address, timeout=20.0)
                    self._disconnected.clear()
                    self._stop.clear()
                    await self._connect_once(device, timeout=40.0)
                    continue
                except Exception as exc:  # noqa: BLE001
                    await self._emit_status(f"Reconnect fehlgeschlagen: {exc}")
                    await asyncio.sleep(2.0)
                    continue
            return

    async def stop(self) -> None:
        self._user_stop = True
        self._stop.set()
        client = self._client
        self._client = None
        if client and client.is_connected:
            for uuid in (self._rower_uuid, HR_MEASUREMENT_UUID):
                if not uuid:
                    continue
                try:
                    await client.stop_notify(uuid)
                except Exception:  # noqa: BLE001
                    pass
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        if self._address and self._adapter:
            await asyncio.to_thread(disconnect_device, self._adapter, self._address)
