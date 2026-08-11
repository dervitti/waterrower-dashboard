"""BlueZ helpers: Adapter-MAC + Discovery/Connect über D-Bus (busctl).

bluetoothctl select gilt nur in einer Session und braucht die Controller-MAC.
Über /org/bluez/hciN/... adressieren wir den Adapter direkt — kein select nötig.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def list_hci_adapters() -> list[str]:
    root = Path("/sys/class/bluetooth")
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.name.startswith("hci") and p.is_dir())


def controller_mac(adapter: str | None) -> str | None:
    """Controller-BDADDR für hciN — sysfs, busctl, bluetoothctl list."""
    if not adapter:
        return None

    for candidate in (
        Path(f"/sys/class/bluetooth/{adapter}/address"),
        Path(f"/sys/kernel/debug/bluetooth/{adapter}/address"),
    ):
        try:
            if candidate.is_file():
                mac = candidate.read_text(encoding="utf-8").strip().upper()
                if mac and re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
                    return mac
        except OSError:
            continue

    mac = _mac_from_busctl(adapter)
    if mac:
        return mac

    mac = _mac_from_bluetoothctl_list(adapter)
    if mac:
        return mac

    try:
        r = subprocess.run(
            ["hciconfig", adapter],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in (r.stdout or "").splitlines():
            if "BD Address:" in line:
                return line.split("BD Address:")[-1].split()[0].strip().upper()
    except Exception:  # noqa: BLE001
        pass
    return None


def _mac_from_busctl(adapter: str) -> str | None:
    if not shutil.which("busctl"):
        return None
    try:
        r = subprocess.run(
            [
                "busctl",
                "get-property",
                "org.bluez",
                f"/org/bluez/{adapter}",
                "org.bluez.Adapter1",
                "Address",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        # s "AA:BB:CC:DD:EE:FF"
        m = re.search(r'"([0-9A-Fa-f:]{17})"', r.stdout or "")
        if m:
            return m.group(1).upper()
    except Exception as exc:  # noqa: BLE001
        logger.debug("busctl Address %s: %s", adapter, exc)
    return None


def _mac_from_bluetoothctl_list(adapter: str) -> str | None:
    if not shutil.which("bluetoothctl"):
        return None
    try:
        r = subprocess.run(
            ["bluetoothctl", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        # Controller AA:BB:… hci1 [default]
        for line in (r.stdout or "").splitlines():
            if adapter in line.split():
                m = re.search(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})", line)
                if m:
                    return m.group(1).upper()
    except Exception as exc:  # noqa: BLE001
        logger.debug("bluetoothctl list: %s", exc)
    return None


def device_object_path(adapter: str, address: str) -> str:
    dev = address.upper().replace(":", "_")
    return f"/org/bluez/{adapter}/dev_{dev}"


def _busctl(*args: str, timeout: float = 20.0) -> tuple[int, str]:
    if not shutil.which("busctl"):
        return 1, "busctl not found"
    try:
        r = subprocess.run(
            ["busctl", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode, out
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _get_bool_prop(path: str, iface: str, prop: str) -> bool | None:
    code, out = _busctl("get-property", "org.bluez", path, iface, prop, timeout=8)
    if code != 0:
        return None
    # b true / b false
    if "true" in out.lower():
        return True
    if "false" in out.lower():
        return False
    return None


def adapter_discovering(adapter: str) -> bool | None:
    return _get_bool_prop(f"/org/bluez/{adapter}", "org.bluez.Adapter1", "Discovering")


def start_discovery(adapter: str) -> str:
    code, out = _busctl(
        "call",
        "org.bluez",
        f"/org/bluez/{adapter}",
        "org.bluez.Adapter1",
        "StartDiscovery",
        timeout=10,
    )
    return f"StartDiscovery rc={code} {out}".strip()


def stop_discovery(adapter: str) -> str:
    if adapter_discovering(adapter) is False:
        return "StopDiscovery skipped (not discovering)"
    code, out = _busctl(
        "call",
        "org.bluez",
        f"/org/bluez/{adapter}",
        "org.bluez.Adapter1",
        "StopDiscovery",
        timeout=10,
    )
    # BlueZ: Discovery kann schon von allein enden
    if code != 0 and "No discovery started" in out:
        return "StopDiscovery already idle"
    return f"StopDiscovery rc={code} {out}".strip()


def set_powered(adapter: str, on: bool = True) -> str:
    code, out = _busctl(
        "set-property",
        "org.bluez",
        f"/org/bluez/{adapter}",
        "org.bluez.Adapter1",
        "Powered",
        "b",
        "true" if on else "false",
        timeout=8,
    )
    return f"Powered rc={code} {out}".strip()


def device_exists(adapter: str, address: str) -> bool:
    path = device_object_path(adapter, address)
    code, _ = _busctl(
        "get-property",
        "org.bluez",
        path,
        "org.bluez.Device1",
        "Address",
        timeout=5,
    )
    return code == 0


def set_trusted(adapter: str, address: str, trusted: bool = True) -> str:
    path = device_object_path(adapter, address)
    code, out = _busctl(
        "set-property",
        "org.bluez",
        path,
        "org.bluez.Device1",
        "Trusted",
        "b",
        "true" if trusted else "false",
        timeout=8,
    )
    return f"Trusted rc={code} {out}".strip()


def connect_device(adapter: str, address: str, timeout: float = 35.0) -> str:
    path = device_object_path(adapter, address)
    code, out = _busctl(
        "call",
        "org.bluez",
        path,
        "org.bluez.Device1",
        "Connect",
        timeout=timeout,
    )
    return f"Connect rc={code} {out}".strip()


def disconnect_device(adapter: str, address: str) -> str:
    path = device_object_path(adapter, address)
    code, out = _busctl(
        "call",
        "org.bluez",
        path,
        "org.bluez.Device1",
        "Disconnect",
        timeout=15,
    )
    return f"Disconnect rc={code} {out}".strip()


def device_flags(adapter: str, address: str) -> dict[str, str]:
    path = device_object_path(adapter, address)
    flags: dict[str, str] = {}
    for prop in ("Connected", "ServicesResolved", "Paired", "Trusted"):
        val = _get_bool_prop(path, "org.bluez.Device1", prop)
        if val is None:
            flags[prop] = "?"
        else:
            flags[prop] = "yes" if val else "no"
    return flags


def remove_device(adapter: str, address: str) -> str:
    path = device_object_path(adapter, address)
    code, out = _busctl(
        "call",
        "org.bluez",
        f"/org/bluez/{adapter}",
        "org.bluez.Adapter1",
        "RemoveDevice",
        "o",
        path,
        timeout=15,
    )
    return f"RemoveDevice rc={code} {out}".strip()


def busctl_tree(service: str = "org.bluez") -> str:
    """busctl tree SERVICE — kein Objektpfad als Argument."""
    if not shutil.which("busctl"):
        return ""
    code, out = _busctl("tree", service, timeout=20)
    return out if code == 0 else f"(tree rc={code}) {out}"


def get_string_prop(path: str, iface: str, prop: str) -> str | None:
    code, out = _busctl(
        "get-property", "org.bluez", path, iface, prop, timeout=8
    )
    if code != 0:
        return None
    m = re.search(r'"([^"]*)"', out)
    return m.group(1) if m else out.strip() or None


def list_gatt_from_busctl_tree(adapter: str, address: str) -> list[str]:
    """GATT-Pfade unter dem Device aus `busctl tree org.bluez`."""
    path = device_object_path(adapter, address)
    tree = busctl_tree("org.bluez")
    children: list[str] = []
    for line in tree.splitlines():
        if path not in line:
            continue
        if "/service" in line or "/char" in line:
            m = re.search(r"(/org/bluez/\S+)", line)
            if m:
                children.append(m.group(1).rstrip(" │├└─"))
    return children


def set_adapter_powered(adapter: str, on: bool) -> str:
    return set_powered(adapter, on)


def wait_services_resolved(
    adapter: str,
    address: str,
    *,
    scan_seconds: float = 5.0,
    wait_seconds: float = 25.0,
    log: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Discovery auf hciN, dann Connect, bis ServicesResolved=yes."""

    def _log(msg: str) -> None:
        if log:
            log(msg)
        else:
            logger.info(msg)

    _log(set_powered(adapter, True))
    flags = device_flags(adapter, address) if device_exists(adapter, address) else {}
    if flags.get("Connected") == "yes" and flags.get("ServicesResolved") == "yes":
        _log("bereits Connected + ServicesResolved")
        return flags

    if flags.get("Connected") == "yes" and flags.get("ServicesResolved") != "yes":
        _log(disconnect_device(adapter, address))
        time.sleep(0.4)

    _log(start_discovery(adapter))
    time.sleep(scan_seconds)
    _log(stop_discovery(adapter))
    time.sleep(0.3)

    if not device_exists(adapter, address):
        _log(f"Gerät nach Scan nicht unter {adapter} — nochmal Discovery…")
        _log(start_discovery(adapter))
        time.sleep(scan_seconds + 2.0)
        _log(stop_discovery(adapter))

    if not device_exists(adapter, address):
        _log(f"FAIL: {address} existiert nicht auf {adapter}")
        return {"Connected": "no", "ServicesResolved": "no", "error": "not available"}

    _log(set_trusted(adapter, address, True))
    _log(connect_device(adapter, address))

    deadline = time.monotonic() + wait_seconds
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = device_flags(adapter, address)
        _log(f"  Connected={last.get('Connected')}  ServicesResolved={last.get('ServicesResolved')}")
        if last.get("Connected") == "no":
            return last
        if last.get("ServicesResolved") == "yes":
            return last
        time.sleep(0.45)
    return last


def btctl_session(commands: list[str], *, controller: str | None = None, timeout: float = 45.0) -> str:
    """Optional: bluetoothctl-Session mit select <MAC>."""
    if not shutil.which("bluetoothctl"):
        return ""
    cmds = list(commands)
    if controller:
        cmds = [f"select {controller}", *cmds]
    script = "\n".join(cmds) + "\nyes\nquit\n"
    try:
        r = subprocess.run(
            ["bluetoothctl"],
            input=script,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
