"""Idle/Sleep und Screen-Lock verhindern während eines Workouts (Linux).

Schichten (alles best-effort):
1. systemd-inhibit idle:sleep — blockiert Suspend via logind
2. xdg-desktop-portal / ScreenSaver Inhibit — wenn der Desktop das versteht
3. SIGSTOP auf swayidle/hypridle — zuverlässig unter Sway (swayidle sperrt
   sonst trotzdem, weil Screen-Lock kein logind-Idle-Inhibit ist)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import signal
import sys

logger = logging.getLogger(__name__)

_IDLE_DAEMONS = ("swayidle", "hypridle")


class IdleInhibit:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._paused_pids: list[int] = []
        self._screensaver_cookie: int | None = None
        self._portal_request: str | None = None

    @property
    def active(self) -> bool:
        return (
            (self._proc is not None and self._proc.returncode is None)
            or bool(self._paused_pids)
            or self._screensaver_cookie is not None
            or self._portal_request is not None
        )

    async def acquire(self, reason: str = "WaterRower Training") -> None:
        if not sys.platform.startswith("linux"):
            return
        await self.release()
        await self._start_systemd_inhibit(reason)
        await self._pause_idle_daemons()
        await self._dbus_screensaver_inhibit(reason)
        await self._portal_inhibit(reason)
        if self.active:
            logger.info(
                "Idle-Inhibit aktiv (systemd=%s, paused=%s, screensaver=%s, portal=%s)",
                self._proc is not None and self._proc.returncode is None,
                self._paused_pids,
                self._screensaver_cookie,
                self._portal_request is not None,
            )
        else:
            logger.warning("Kein Idle-Inhibit möglich — nur Browser-Wake-Lock")

    async def release(self) -> None:
        await self._stop_systemd_inhibit()
        await self._resume_idle_daemons()
        await self._dbus_screensaver_uninhibit()
        await self._portal_uninhibit()

    async def _start_systemd_inhibit(self, reason: str) -> None:
        inhibit = shutil.which("systemd-inhibit")
        if not inhibit:
            return
        try:
            self._proc = await asyncio.create_subprocess_exec(
                inhibit,
                "--what=idle:sleep",
                "--who=WaterRower",
                f"--why={reason}",
                "--mode=block",
                "sleep",
                "infinity",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("systemd-inhibit fehlgeschlagen: %s", exc)
            self._proc = None

    async def _stop_systemd_inhibit(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Inhibit release: %s", exc)

    async def _pause_idle_daemons(self) -> None:
        """swayidle respektiert Screen-Lock nicht über logind — pausieren."""
        pgrep = shutil.which("pgrep")
        if not pgrep:
            return
        uid = os.getuid()
        paused: list[int] = []
        for name in _IDLE_DAEMONS:
            try:
                proc = await asyncio.create_subprocess_exec(
                    pgrep,
                    "-u",
                    str(uid),
                    "-x",
                    name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await proc.communicate()
            except Exception as exc:  # noqa: BLE001
                logger.debug("pgrep %s: %s", name, exc)
                continue
            for line in out.decode().splitlines():
                line = line.strip()
                if not line.isdigit():
                    continue
                pid = int(line)
                try:
                    os.kill(pid, signal.SIGSTOP)
                    paused.append(pid)
                    logger.info("%s (pid %s) pausiert für Training", name, pid)
                except ProcessLookupError:
                    continue
                except PermissionError as exc:
                    logger.warning("Kann %s (%s) nicht pausieren: %s", name, pid, exc)
        self._paused_pids = paused

    async def _resume_idle_daemons(self) -> None:
        pids = self._paused_pids
        self._paused_pids = []
        for pid in pids:
            try:
                os.kill(pid, signal.SIGCONT)
                logger.info("Idle-Daemon pid %s fortgesetzt", pid)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                logger.warning("Kann pid %s nicht fortsetzen: %s", pid, exc)

    async def _run_gdbus(self, *args: str) -> str | None:
        gdbus = shutil.which("gdbus")
        if not gdbus:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                gdbus,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            logger.debug("gdbus %s: %s", args[:3], exc)
            return None
        if proc.returncode != 0:
            logger.debug(
                "gdbus failed (%s): %s",
                proc.returncode,
                (err or b"").decode(errors="replace")[:200],
            )
            return None
        return out.decode(errors="replace").strip()

    async def _dbus_screensaver_inhibit(self, reason: str) -> None:
        out = await self._run_gdbus(
            "call",
            "--session",
            "--dest",
            "org.freedesktop.ScreenSaver",
            "--object-path",
            "/org/freedesktop/ScreenSaver",
            "--method",
            "org.freedesktop.ScreenSaver.Inhibit",
            "WaterRower",
            reason,
        )
        if not out:
            return
        # typ. Antwort: (uint32 42,)
        m = re.search(r"\bu?int32\s+(\d+)\b|\((\d+),", out)
        if m:
            self._screensaver_cookie = int(m.group(1) or m.group(2))
            logger.info("ScreenSaver Inhibit cookie=%s", self._screensaver_cookie)

    async def _dbus_screensaver_uninhibit(self) -> None:
        cookie = self._screensaver_cookie
        self._screensaver_cookie = None
        if cookie is None:
            return
        await self._run_gdbus(
            "call",
            "--session",
            "--dest",
            "org.freedesktop.ScreenSaver",
            "--object-path",
            "/org/freedesktop/ScreenSaver",
            "--method",
            "org.freedesktop.ScreenSaver.UnInhibit",
            str(cookie),
        )

    async def _portal_inhibit(self, reason: str) -> None:
        # flags: 4=suspend, 8=idle
        out = await self._run_gdbus(
            "call",
            "--session",
            "--dest",
            "org.freedesktop.portal.Desktop",
            "--object-path",
            "/org/freedesktop/portal/desktop",
            "--method",
            "org.freedesktop.portal.Inhibit.Inhibit",
            "",
            "uint32:12",
            f"{{'reason': <'{reason}'>}}",
        )
        if not out:
            return
        # (objectpath '/org/freedesktop/portal/desktop/request/...')
        if "'/" in out:
            path = out.split("'", 2)[1]
            self._portal_request = path
            logger.info("Portal Inhibit: %s", path)

    async def _portal_uninhibit(self) -> None:
        path = self._portal_request
        self._portal_request = None
        if not path:
            return
        # Close the request object to drop the inhibit
        await self._run_gdbus(
            "call",
            "--session",
            "--dest",
            "org.freedesktop.portal.Desktop",
            "--object-path",
            path,
            "--method",
            "org.freedesktop.portal.Request.Close",
        )


idle_inhibit = IdleInhibit()
