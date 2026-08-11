"""FTMS over BlueZ D-Bus (ohne Bleak-GATT-Cache).

Wichtig: Desktop-BT (Sway/blueman) darf das ComModule nicht parallel
connect/disconnecten — sonst stirbt der Link vor GATT-Export.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from dbus_fast import BusType, Message, MessageType, Variant, unpack_variants
from dbus_fast.aio import MessageBus

from app.ble.bluez_util import (
    busctl_tree,
    connect_device,
    controller_mac,
    device_exists,
    device_flags,
    device_object_path,
    disconnect_device,
    get_string_prop,
    list_gatt_from_busctl_tree,
    list_hci_adapters,
    remove_device,
    set_powered,
    set_trusted,
    start_discovery,
    stop_discovery,
)
from app.ble.parser import ParsedRowerData, parse_rower_data
from app.config import ROWER_DATA_UUID

logger = logging.getLogger(__name__)

BLUEZ = "org.bluez"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = "org.freedesktop.DBus.Properties"
DEVICE_IFACE = "org.bluez.Device1"
SERVICE_IFACE = "org.bluez.GattService1"
CHAR_IFACE = "org.bluez.GattCharacteristic1"
DBUS = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
HR_UUID_NEEDLE = "2a37"
ROWER_NEEDLE = "2ad1"

MetricsCallback = Callable[[ParsedRowerData], Awaitable[None] | None]
StatusCallback = Callable[[str], Awaitable[None] | None]


def resolve_ble_adapter() -> str | None:
    env = os.environ.get("WR_BLE_ADAPTER", "").strip()
    if env:
        return env
    adapters = list_hci_adapters()
    if not adapters:
        return None
    if len(adapters) == 1:
        return adapters[0]
    for name in reversed(adapters):
        if name != "hci0":
            return name
    return adapters[-1]


def _uuid_norm(u: str) -> str:
    return u.lower().replace("-", "")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class BluezFtmsClient:
    def __init__(
        self,
        on_metrics: MetricsCallback,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._on_metrics = on_metrics
        self._on_status = on_status
        self._adapter: str | None = None
        self._address: str | None = None
        self._device_name: str | None = None
        self._bus: MessageBus | None = None
        self._device_path: str | None = None
        self._rower_path: str | None = None
        self._hr_path: str | None = None
        self._stop = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._user_stop = False
        self._connected = False
        self._handlers: list[Callable[[Message], None]] = []
        self._monitor_task: asyncio.Task[None] | None = None
        self._added_paths: list[str] = []

    @property
    def device_name(self) -> str | None:
        return self._device_name

    @property
    def connected(self) -> bool:
        return self._connected and not self._disconnected.is_set()

    async def _emit(self, msg: str) -> None:
        logger.info("bluez-ftms: %s", msg)
        if self._on_status:
            r = self._on_status(msg)
            if asyncio.iscoroutine(r):
                await r

    async def _add_match(self, rule: str) -> None:
        assert self._bus
        reply = await self._bus.call(
            Message(
                destination=DBUS,
                path=DBUS_PATH,
                interface=DBUS,
                member="AddMatch",
                signature="s",
                body=[rule],
            )
        )
        if reply.message_type == MessageType.ERROR:
            logger.warning("AddMatch failed: %s %s", reply.error_name, reply.body)

    async def _get_managed_objects(self) -> dict[str, Any]:
        assert self._bus
        reply = await self._bus.call(
            Message(
                destination=BLUEZ,
                path="/",
                interface=OBJECT_MANAGER,
                member="GetManagedObjects",
            )
        )
        if reply.message_type != MessageType.METHOD_RETURN:
            raise RuntimeError(f"GetManagedObjects failed: {reply.error_name}")
        return unpack_variants(reply.body[0])

    def _on_interfaces_added(self, msg: Message) -> None:
        if msg.message_type != MessageType.SIGNAL or msg.member != "InterfacesAdded":
            return
        if not msg.body:
            return
        path = str(msg.body[0])
        if self._device_path and path.startswith(self._device_path):
            self._added_paths.append(path)
            logger.info("InterfacesAdded: %s", path)

    async def _wait_connected_resolved(self, seconds: float = 25.0) -> dict[str, str]:
        assert self._adapter and self._address
        deadline = time.monotonic() + seconds
        last = ""
        while time.monotonic() < deadline:
            flags = await asyncio.to_thread(device_flags, self._adapter, self._address)
            sig = f"{flags.get('Connected')}/{flags.get('ServicesResolved')}"
            if sig != last:
                await self._emit(
                    f"Link Connected={flags.get('Connected')} "
                    f"ServicesResolved={flags.get('ServicesResolved')}"
                )
                last = sig
            if flags.get("Connected") == "yes" and flags.get("ServicesResolved") == "yes":
                return flags
            if flags.get("Connected") == "no" and last.startswith("yes"):
                return flags  # peer drop
            await asyncio.sleep(0.2)
        return await asyncio.to_thread(device_flags, self._adapter, self._address)

    async def _diagnose_gatt(self) -> str:
        assert self._adapter and self._address and self._device_path
        flags = await asyncio.to_thread(device_flags, self._adapter, self._address)
        uuids = await asyncio.to_thread(
            get_string_prop, self._device_path, DEVICE_IFACE, "UUIDs"
        )
        tree = await asyncio.to_thread(busctl_tree, "org.bluez")
        # nur Device-Zweig
        tree_lines = [ln for ln in tree.splitlines() if self._device_path in ln]
        tree_children = await asyncio.to_thread(
            list_gatt_from_busctl_tree, self._adapter, self._address
        )
        objs = await self._get_managed_objects()
        under = [p for p in objs if p.startswith(self._device_path + "/")]
        services = [p for p in under if SERVICE_IFACE in (objs.get(p) or {})]
        chars = [p for p in under if CHAR_IFACE in (objs.get(p) or {})]
        global_rower: list[str] = []
        for path, ifaces in objs.items():
            char = (ifaces or {}).get(CHAR_IFACE) or {}
            uuid = str(char.get("UUID", ""))
            if ROWER_NEEDLE in _uuid_norm(uuid):
                global_rower.append(path)
        return "\n".join(
            [
                f"flags={flags}",
                f"Device.UUIDs={uuids!r}",
                f"InterfacesAdded während Wait: {len(self._added_paths)}",
                f"managed under device: {len(under)} (services={len(services)} chars={len(chars)})",
                f"busctl tree children: {len(tree_children)}",
                f"global 2AD1 paths: {global_rower or '—'}",
                "busctl tree (device branch):",
                "\n".join(tree_lines[:40]) if tree_lines else "(kein Eintrag)",
                "",
                "Hinweis: Wenn Sway/blueman Popups 'S4 Comms getrennt' zeigen,",
                "Desktop-BT konkurriert — siehe Probe-Ausgabe.",
            ]
        )

    async def _find_chars(self) -> tuple[str | None, str | None, list[str]]:
        assert self._device_path
        objs = await self._get_managed_objects()
        rower = hr = None
        found: list[str] = []
        addr = (self._address or "").upper()

        for path, ifaces in objs.items():
            char = (ifaces or {}).get(CHAR_IFACE)
            if not char:
                continue
            uuid = str(char.get("UUID", ""))
            n = _uuid_norm(uuid)
            m = re.search(r"dev_([0-9A-Fa-f_]+)", path)
            if not m:
                continue
            if m.group(1).replace("_", ":").upper() != addr:
                continue
            found.append(uuid)
            if ROWER_NEEDLE in n or _uuid_norm(ROWER_DATA_UUID) == n:
                rower = path
            if HR_UUID_NEEDLE in n:
                hr = path
        return rower, hr, found

    async def _wait_gatt(self, seconds: float = 15.0) -> bool:
        deadline = time.monotonic() + seconds
        last_n = -1
        while time.monotonic() < deadline:
            flags = await asyncio.to_thread(
                device_flags, self._adapter or "", self._address or ""
            )
            if flags.get("Connected") != "yes":
                await self._emit(
                    "Link weg während GATT-Wait "
                    "(oft Desktop-BT oder zweiter Adapter) — Abbruch"
                )
                return False
            rower, hr, found = await self._find_chars()
            if len(found) != last_n:
                await self._emit(f"GATT chars sichtbar: {len(found)}")
                last_n = len(found)
            if rower:
                self._rower_path = rower
                self._hr_path = hr
                self._device_path = rower.split("/service")[0]
                return True
            await asyncio.sleep(0.25)
        return False

    async def _ensure_device_on_adapter(self, seconds: float = 20.0) -> None:
        """Device-Objekt muss unter /org/bluez/hciN/dev_… existieren (nach Scan)."""
        assert self._adapter and self._address and self._device_path
        if await asyncio.to_thread(device_exists, self._adapter, self._address):
            await self._emit(f"Device-Objekt OK: {self._device_path}")
            return
        await self._emit(
            f"Kein Device-Objekt auf {self._adapter} — Discovery {seconds:.0f}s…"
        )
        await asyncio.to_thread(set_powered, self._adapter, True)
        await asyncio.to_thread(start_discovery, self._adapter)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if await asyncio.to_thread(device_exists, self._adapter, self._address):
                await asyncio.to_thread(stop_discovery, self._adapter)
                self._device_path = device_object_path(self._adapter, self._address)
                await self._emit(f"Device gefunden: {self._device_path}")
                return
            await asyncio.sleep(0.4)
        await asyncio.to_thread(stop_discovery, self._adapter)
        # Nochmal Bleak-Scan als Fallback (legt Device oft in BlueZ an)
        try:
            from bleak import BleakScanner

            await self._emit("Bleak-Scan Fallback…")
            bluez = {"adapter": self._adapter}
            dev = await BleakScanner.find_device_by_address(
                self._address, timeout=min(seconds, 12.0), bluez=bluez
            )
            if dev and await asyncio.to_thread(device_exists, self._adapter, self._address):
                self._device_path = device_object_path(self._adapter, self._address)
                await self._emit(f"Device nach Bleak-Scan: {self._device_path}")
                return
            if dev and getattr(dev, "details", None):
                path = (dev.details or {}).get("path")
                if path:
                    self._device_path = path
                    await self._emit(f"Device-Pfad aus Bleak: {path}")
                    return
        except Exception as exc:  # noqa: BLE001
            logger.info("Bleak ensure device: %s", exc)
        raise RuntimeError(
            f"Gerät {self._address} erscheint nicht auf {self._adapter}. "
            "ComModule wach (PC-Symbol), näher an den Dongle, Phone-BLE aus."
        )

    async def _connect_on_bus(self, timeout: float) -> None:
        assert self._bus and self._device_path and self._adapter and self._address
        force = _env_flag("WR_BLE_FORCE_RECONNECT", False)

        if not await asyncio.to_thread(device_exists, self._adapter, self._address):
            await self._ensure_device_on_adapter(15.0)

        flags = await asyncio.to_thread(device_flags, self._adapter, self._address)
        if flags.get("Connected") == "yes" and flags.get("ServicesResolved") == "yes":
            await self._emit("Bereits Connected+ServicesResolved — kein Reconnect")
            return
        if flags.get("Connected") == "yes" and force:
            await self._emit("WR_BLE_FORCE_RECONNECT: Disconnect…")
            await asyncio.to_thread(disconnect_device, self._adapter, self._address)
            await asyncio.sleep(0.6)

        async def _once() -> tuple[bool, str]:
            assert self._bus and self._device_path
            reply = await asyncio.wait_for(
                self._bus.call(
                    Message(
                        destination=BLUEZ,
                        path=self._device_path,
                        interface=DEVICE_IFACE,
                        member="Connect",
                    )
                ),
                timeout=timeout,
            )
            if reply.message_type != MessageType.ERROR:
                return True, "OK"
            return False, f"{reply.error_name} {reply.body}"

        ok, err = await _once()
        if ok:
            await self._emit("Connect OK (D-Bus-Session)")
            return
        if "Already Connected" in err or "InProgress" in err:
            await self._emit(f"Connect: {err} (ok)")
            return

        # UnknownObject / kein Device1 → neu scannen und 1× retry
        if "UnknownObject" in err or "doesn't exist" in err or "UnknownMethod" in err:
            await self._emit(f"Connect: Objekt weg ({err[:80]}…) — Discovery+Retry")
            await self._ensure_device_on_adapter(18.0)
            await asyncio.to_thread(set_trusted, self._adapter, self._address, True)
            ok, err = await _once()
            if ok or "Already Connected" in err:
                await self._emit("Connect OK nach Rediscovery")
                return

        out = await asyncio.to_thread(
            connect_device, self._adapter, self._address, timeout
        )
        await self._emit(f"Connect busctl fallback: {out}")
        if "rc=0" not in out and "Already" not in out:
            raise RuntimeError(f"Connect failed: {err} / {out}")

    async def _optional_refresh(self) -> None:
        if not _env_flag("WR_BLE_REFRESH", False):
            return
        assert self._adapter and self._address
        await self._emit("WR_BLE_REFRESH=1 — RemoveDevice + Rediscovery…")
        await asyncio.to_thread(disconnect_device, self._adapter, self._address)
        for a in list_hci_adapters():
            try:
                await asyncio.to_thread(remove_device, a, self._address)
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.5)
        await asyncio.to_thread(start_discovery, self._adapter)
        await asyncio.sleep(6.0)
        await asyncio.to_thread(stop_discovery, self._adapter)
        self._device_path = device_object_path(self._adapter, self._address)
        await asyncio.to_thread(set_trusted, self._adapter, self._address, True)
        await self._connect_on_bus(40.0)

    def _make_value_handler(
        self, char_path: str, handler: Callable[[bytearray], None]
    ) -> Callable[[Message], None]:
        def _handle(msg: Message) -> None:
            if msg.message_type != MessageType.SIGNAL:
                return
            if msg.member != "PropertiesChanged":
                return
            if msg.path != char_path:
                return
            if not msg.body or len(msg.body) < 2:
                return
            iface = msg.body[0]
            changed = unpack_variants(msg.body[1])
            if iface != CHAR_IFACE or not isinstance(changed, dict):
                return
            if "Value" not in changed:
                return
            raw = changed["Value"]
            if isinstance(raw, Variant):
                raw = raw.value
            if isinstance(raw, (bytes, bytearray)):
                try:
                    handler(bytearray(raw))
                except Exception:  # noqa: BLE001
                    logger.exception("notify handler failed")

        return _handle

    async def _start_notify(
        self, char_path: str, handler: Callable[[bytearray], None]
    ) -> None:
        assert self._bus
        h = self._make_value_handler(char_path, handler)
        self._handlers.append(h)
        self._bus.add_message_handler(h)
        reply = await self._bus.call(
            Message(
                destination=BLUEZ,
                path=char_path,
                interface=CHAR_IFACE,
                member="StartNotify",
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(
                f"StartNotify {char_path}: {reply.error_name} {reply.body}"
            )

    def _dispatch_metrics(self, parsed: ParsedRowerData) -> None:
        result = self._on_metrics(parsed)
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)

    def _on_rower(self, data: bytearray) -> None:
        try:
            self._dispatch_metrics(parse_rower_data(data))
        except Exception:  # noqa: BLE001
            logger.exception("rower parse failed: %s", data.hex())

    def _on_hr(self, data: bytearray) -> None:
        try:
            if not data:
                return
            flags = data[0]
            hr = data[1] if (flags & 0x01) == 0 else int.from_bytes(data[1:3], "little")
            self._dispatch_metrics(ParsedRowerData(heart_rate=hr))
        except Exception:  # noqa: BLE001
            logger.exception("hr parse failed")

    async def _resolve_address(self, address: str | None, timeout: float) -> str:
        if address:
            return address.upper()
        assert self._adapter
        await self._emit("Suche ComModule (D-Bus Discovery)…")
        await asyncio.to_thread(set_powered, self._adapter, True)
        await asyncio.to_thread(start_discovery, self._adapter)
        deadline = time.monotonic() + timeout
        found: str | None = None
        while time.monotonic() < deadline:
            objs = await self._get_managed_objects()
            prefix = f"/org/bluez/{self._adapter}/dev_"
            for path, ifaces in objs.items():
                if not path.startswith(prefix) or path.count("/") != 4:
                    continue
                dev = (ifaces or {}).get(DEVICE_IFACE)
                if not dev:
                    continue
                name = str(dev.get("Name") or dev.get("Alias") or "")
                uuids = [_uuid_norm(str(u)) for u in (dev.get("UUIDs") or [])]
                looks = any(
                    k in name.lower() for k in ("water", "comm", "wr", "s4", "rower")
                )
                looks = looks or any("1826" in u for u in uuids)
                if looks:
                    found = str(dev.get("Address", "")).upper()
                    if found:
                        break
            if found:
                break
            await asyncio.sleep(0.5)
        await asyncio.to_thread(stop_discovery, self._adapter)
        if not found:
            raise RuntimeError("Kein FTMS/ComModule gefunden.")
        return found

    async def connect(self, address: str | None = None, timeout: float = 40.0) -> None:
        self._adapter = resolve_ble_adapter()
        if not self._adapter:
            raise RuntimeError("Kein BLE-Adapter (WR_BLE_ADAPTER setzen).")

        self._stop.clear()
        self._disconnected.clear()
        self._user_stop = False
        self._connected = False
        self._added_paths.clear()

        ctrl = controller_mac(self._adapter)
        adapters = list_hci_adapters()
        await self._emit(
            f"Adapter: {self._adapter}"
            + (f" ({ctrl})" if ctrl else "")
            + f" (verfügbar: {', '.join(adapters) or '—'})"
        )
        await self._emit(
            "Wichtig: Sway/blueman darf S4 Comms nicht parallel verbinden. "
            "hci0 aus: busctl set-property org.bluez /org/bluez/hci0 "
            "org.bluez.Adapter1 Powered b false"
        )

        # Optional: internen Adapter stumm schalten
        if _env_flag("WR_BLE_DISABLE_HCI0", True) and self._adapter != "hci0":
            if "hci0" in adapters:
                await asyncio.to_thread(set_powered, "hci0", False)
                await self._emit("hci0 Powered=false (WR_BLE_DISABLE_HCI0)")

        self._bus = MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True)
        await self._bus.connect()
        await self._add_match(
            "type='signal',sender='org.bluez',"
            "interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',"
            "path_namespace='/org/bluez'"
        )
        await self._add_match(
            "type='signal',sender='org.bluez',"
            "interface='org.freedesktop.DBus.ObjectManager',member='InterfacesAdded',"
            "arg0path='/org/bluez/'"
        )
        self._bus.add_message_handler(self._on_interfaces_added)
        self._handlers.append(self._on_interfaces_added)

        addr = await self._resolve_address(address, min(timeout, 15.0))
        self._address = addr
        self._device_path = device_object_path(self._adapter, addr)
        self._device_name = addr

        await self._ensure_device_on_adapter(min(timeout, 20.0))
        await asyncio.to_thread(set_trusted, self._adapter, addr, True)
        await self._emit(f"D-Bus Connect {addr}…")
        await self._connect_on_bus(timeout)

        flags = await self._wait_connected_resolved(min(timeout, 20.0))
        if flags.get("Connected") != "yes":
            raise RuntimeError(
                "ComModule verbindet kurz und trennt sofort — typisch Desktop-BT "
                "(Sway-Popup) oder Phone noch verbunden. Desktop-BT für dieses Gerät "
                "ignorieren/entfernen, Handy-BLE aus, dann erneut.\n"
                + await self._diagnose_gatt()
            )
        if flags.get("ServicesResolved") != "yes":
            raise RuntimeError(
                "Connected ohne ServicesResolved.\n" + await self._diagnose_gatt()
            )

        await self._emit("ServicesResolved — warte auf GATT-Objekte…")
        ok = await self._wait_gatt(12.0)
        if not ok and _env_flag("WR_BLE_REFRESH", False):
            await self._optional_refresh()
            flags = await self._wait_connected_resolved(20.0)
            if flags.get("Connected") == "yes":
                ok = await self._wait_gatt(12.0)

        if not ok:
            raise RuntimeError(
                "Keine Rower-Data (2AD1) unter D-Bus.\n" + await self._diagnose_gatt()
            )

        assert self._rower_path
        short = re.search(r"char[0-9a-fA-F]+", self._rower_path)
        await self._emit(f"StartNotify {short.group(0) if short else '2AD1'}…")
        await self._start_notify(self._rower_path, self._on_rower)
        if self._hr_path:
            try:
                await self._start_notify(self._hr_path, self._on_hr)
                await self._emit("HR Notify aktiv")
            except Exception as exc:  # noqa: BLE001
                logger.info("HR notify optional: %s", exc)

        name = await self._read_name()
        if name:
            self._device_name = name
        self._connected = True
        await self._emit(f"Verbunden (D-Bus) mit {self._device_name} — Notify aktiv")
        self._monitor_task = asyncio.create_task(self._monitor_link())

    async def _read_name(self) -> str | None:
        if not self._bus or not self._device_path:
            return None
        reply = await self._bus.call(
            Message(
                destination=BLUEZ,
                path=self._device_path,
                interface=PROPERTIES,
                member="Get",
                signature="ss",
                body=[DEVICE_IFACE, "Name"],
            )
        )
        if reply.message_type != MessageType.METHOD_RETURN:
            return None
        val = unpack_variants(reply.body[0])
        if isinstance(val, Variant):
            val = val.value
        return str(val) if val else None

    async def _monitor_link(self) -> None:
        assert self._adapter and self._address
        while not self._stop.is_set() and not self._user_stop:
            flags = await asyncio.to_thread(device_flags, self._adapter, self._address)
            if flags.get("Connected") != "yes":
                self._connected = False
                self._disconnected.set()
                await self._emit("Bluetooth getrennt (D-Bus)")
                return
            await asyncio.sleep(1.0)

    async def run_until_stopped(self) -> None:
        while True:
            wait_stop = asyncio.create_task(self._stop.wait())
            wait_disc = asyncio.create_task(self._disconnected.wait())
            await asyncio.wait(
                {wait_stop, wait_disc},
                return_when=asyncio.FIRST_COMPLETED,
            )
            wait_stop.cancel()
            wait_disc.cancel()
            if self._user_stop or self._disconnected.is_set():
                return

    async def stop(self) -> None:
        self._user_stop = True
        self._stop.set()
        self._connected = False
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None
        bus = self._bus
        self._bus = None
        if bus:
            try:
                for h in self._handlers:
                    try:
                        bus.remove_message_handler(h)
                    except Exception:  # noqa: BLE001
                        pass
                bus.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._handlers.clear()
        if self._adapter and self._address:
            await asyncio.to_thread(disconnect_device, self._adapter, self._address)
