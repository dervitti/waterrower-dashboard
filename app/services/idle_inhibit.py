"""Idle/Sleep verhindern während eines Workouts (Linux).

Nutzt systemd-inhibit (idle + sleep), damit Sway/logind den Rechner
nicht in Standby schickt solange das Training läuft.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

logger = logging.getLogger(__name__)


class IdleInhibit:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def acquire(self, reason: str = "WaterRower Training") -> None:
        if not sys.platform.startswith("linux"):
            return
        await self.release()
        inhibit = shutil.which("systemd-inhibit")
        if not inhibit:
            logger.info("systemd-inhibit nicht gefunden — nur Browser-Wake-Lock")
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
            logger.info("Idle/Sleep inhibit aktiv (%s)", reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Idle-Inhibit fehlgeschlagen: %s", exc)
            self._proc = None

    async def release(self) -> None:
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
            logger.info("Idle/Sleep inhibit beendet")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Inhibit release: %s", exc)


idle_inhibit = IdleInhibit()
