"""Coordinates live workout: BLE/demo → DB samples → WebSocket fans."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from app.ble.bluez_ftms import BluezFtmsClient
from app.ble.client import FtmsRowerClient
from app.ble.parser import ParsedRowerData
from app.ble.simulator import DemoRower
from app.ble.usb_s4 import UsbRowerClient
from app.config import SAMPLE_INTERVAL_SEC
from app.db import SessionLocal
from app.hr_zones import effective_max_hr
from app.models import TelemetrySample, User, WorkoutSession
from app.schemas import RowerMetrics, WorkoutStatus
from app.services.idle_inhibit import idle_inhibit

logger = logging.getLogger(__name__)


class WorkoutManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._clients: set[WebSocket] = set()
        self._source: FtmsRowerClient | BluezFtmsClient | DemoRower | UsbRowerClient | None = None
        self._mode: str | None = None
        self._user_id: int | None = None
        self._user_name: str | None = None
        self._session_id: int | None = None
        self._started_monotonic: float | None = None
        self._last_sample_at = 0.0
        self._metrics = RowerMetrics()
        self._message: str | None = None
        self._connected = False
        self._user_max_hr: int | None = None
        self._timer_running = False
        self._timer_accum_s = 0.0
        self._timer_started_mono: float | None = None
        self._spm_sum = 0.0
        self._spm_n = 0
        self._pace_sum = 0.0
        self._pace_n = 0
        self._power_sum = 0.0
        self._power_n = 0
        self._hr_sum = 0.0
        self._hr_n = 0
        self._max_hr = 0
        self._max_power = 0

    def _timer_elapsed_s(self) -> int:
        total = self._timer_accum_s
        if self._timer_running and self._timer_started_mono is not None:
            total += time.monotonic() - self._timer_started_mono
        return max(0, int(total))

    def _reset_timer(self) -> None:
        self._timer_running = False
        self._timer_accum_s = 0.0
        self._timer_started_mono = None

    def _apply_auto_timer(self, spm: float | None) -> bool:
        """SPM > 0 → starten, SPM == 0 → pausieren. True bei Zustandswechsel."""
        if spm is None:
            return False
        if spm > 0 and not self._timer_running:
            self._timer_started_mono = time.monotonic()
            self._timer_running = True
            return True
        if spm <= 0 and self._timer_running:
            if self._timer_started_mono is not None:
                self._timer_accum_s += time.monotonic() - self._timer_started_mono
            self._timer_started_mono = None
            self._timer_running = False
            return True
        return False

    def status(self) -> WorkoutStatus:
        metrics = self._metrics.model_copy()
        metrics.elapsed_s = self._timer_elapsed_s()
        return WorkoutStatus(
            active=self._task is not None and not self._task.done(),
            mode=self._mode,
            user_id=self._user_id,
            user_name=self._user_name,
            user_max_hr=self._user_max_hr,
            session_id=self._session_id,
            device_name=getattr(self._source, "device_name", None),
            connected=self._connected or bool(getattr(self._source, "connected", False)),
            metrics=metrics,
            message=self._message,
            timer_running=self._timer_running,
        )

    async def register_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        await ws.send_json({"type": "status", "payload": self.status().model_dump()})

    def unregister_ws(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _set_message(self, message: str) -> None:
        self._message = message
        await self.broadcast({"type": "status", "payload": self.status().model_dump()})

    async def start(
        self,
        user_id: int,
        mode: str = "ble",
        device_address: str | None = None,
        serial_port: str | None = None,
    ) -> WorkoutStatus:
        async with self._lock:
            if self._task and not self._task.done():
                raise RuntimeError("Es läuft bereits ein Workout.")

            db = SessionLocal()
            try:
                user = db.get(User, user_id)
                if not user:
                    raise RuntimeError("User nicht gefunden.")
                session = WorkoutSession(user_id=user.id, source=mode)
                db.add(session)
                db.commit()
                db.refresh(session)
                self._user_id = user.id
                self._user_name = user.name
                self._user_max_hr = effective_max_hr(
                    max_hr_override=user.max_hr,
                    sex=user.sex,
                    birth_year=user.birth_year,
                    weight_kg=user.weight_kg,
                )
                self._session_id = session.id
            finally:
                db.close()

            self._mode = mode
            self._started_monotonic = time.monotonic()
            self._last_sample_at = 0.0
            self._metrics = RowerMetrics()
            self._connected = False
            self._reset_aggregates()
            self._reset_timer()
            await idle_inhibit.acquire(f"WaterRower {mode}-Training")

            if mode == "demo":
                demo = DemoRower(self._on_metrics, self._set_message)
                self._source = demo
                self._task = asyncio.create_task(self._run_demo(demo))
            elif mode == "usb":
                usb = UsbRowerClient(self._on_metrics, self._set_message, port=serial_port)
                self._source = usb
                self._task = asyncio.create_task(self._run_usb(usb))
            else:
                backend = os.environ.get("WR_BLE_BACKEND", "dbus").strip().lower()
                if backend == "bleak" or not sys.platform.startswith("linux"):
                    client: FtmsRowerClient | BluezFtmsClient = FtmsRowerClient(
                        self._on_metrics, self._set_message
                    )
                else:
                    client = BluezFtmsClient(self._on_metrics, self._set_message)
                self._source = client
                self._task = asyncio.create_task(self._run_ble(client, device_address))

            await self.broadcast({"type": "status", "payload": self.status().model_dump()})
            return self.status()

    def _reset_aggregates(self) -> None:
        self._spm_sum = self._spm_n = 0
        self._pace_sum = self._pace_n = 0
        self._power_sum = self._power_n = 0
        self._hr_sum = self._hr_n = 0
        self._max_hr = 0
        self._max_power = 0

    async def _run_usb(self, usb: UsbRowerClient) -> None:
        try:
            await usb.connect()
            self._connected = True
            await self.broadcast({"type": "status", "payload": self.status().model_dump()})
            await usb.run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("USB failed")
            await self._set_message(f"USB-Fehler: {exc}")
        finally:
            await usb.stop()
            await self._finalize_session()

    async def _run_demo(self, demo: DemoRower) -> None:
        try:
            self._connected = True
            await demo.run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Demo failed")
            await self._set_message(f"Demo-Fehler: {exc}")
        finally:
            await self._finalize_session()

    async def _run_ble(
        self, client: FtmsRowerClient | BluezFtmsClient, address: str | None
    ) -> None:
        try:
            await client.connect(address=address)
            self._connected = True
            await self.broadcast({"type": "status", "payload": self.status().model_dump()})
            await client.run_until_stopped()
        except Exception as exc:  # noqa: BLE001
            logger.exception("BLE failed")
            await self._set_message(f"BLE-Fehler: {exc}")
        finally:
            was_disconnect = getattr(client, "_disconnected", None)
            await client.stop()
            await self._finalize_session()
            if was_disconnect is not None and was_disconnect.is_set():
                await self._set_message(
                    "Verbindung vom ComModule getrennt. "
                    "WaterRower-Apps schließen, ComModule kurz aus/an, erneut Start."
                )

    async def stop(self) -> WorkoutStatus:
        async with self._lock:
            source = self._source
            task = self._task
            if source:
                await source.stop()
            if task:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)
                except Exception:  # noqa: BLE001
                    task.cancel()
            return self.status()

    async def timer_start(self) -> WorkoutStatus:
        if not self._timer_running:
            self._timer_started_mono = time.monotonic()
            self._timer_running = True
        status = self.status()
        await self.broadcast({"type": "status", "payload": status.model_dump()})
        return status

    async def timer_pause(self) -> WorkoutStatus:
        if self._timer_running and self._timer_started_mono is not None:
            self._timer_accum_s += time.monotonic() - self._timer_started_mono
            self._timer_started_mono = None
            self._timer_running = False
            self._metrics.elapsed_s = self._timer_elapsed_s()
        status = self.status()
        await self.broadcast({"type": "status", "payload": status.model_dump()})
        await self.broadcast({"type": "metrics", "payload": status.metrics.model_dump()})
        return status

    async def timer_reset(self) -> WorkoutStatus:
        self._reset_timer()
        self._metrics.elapsed_s = 0
        status = self.status()
        await self.broadcast({"type": "status", "payload": status.model_dump()})
        await self.broadcast({"type": "metrics", "payload": status.metrics.model_dump()})
        return status

    async def _on_metrics(self, parsed: ParsedRowerData) -> None:
        prev = self._metrics
        stroke_rate = (
            parsed.stroke_rate if parsed.stroke_rate is not None else prev.stroke_rate
        )
        timer_changed = self._apply_auto_timer(stroke_rate)
        elapsed = self._timer_elapsed_s()
        distance_m = (
            parsed.distance_m if parsed.distance_m is not None else prev.distance_m
        )
        # Ø-Pace /500m aus Timer-Zeit und Distanz (nicht Momentan-Speed)
        pace_s = None
        if elapsed >= 5 and distance_m is not None and distance_m >= 10:
            raw = (elapsed / distance_m) * 500.0
            if 60 < raw < 600:
                pace_s = round(raw, 1)

        metrics = RowerMetrics(
            stroke_rate=stroke_rate,
            stroke_count=parsed.stroke_count if parsed.stroke_count is not None else prev.stroke_count,
            distance_m=distance_m,
            pace_s=pace_s,
            avg_pace_s=pace_s,
            avg_intensity_mps=(
                parsed.avg_intensity_mps
                if parsed.avg_intensity_mps is not None
                else prev.avg_intensity_mps
            ),
            power_w=parsed.power_w if parsed.power_w is not None else prev.power_w,
            avg_power_w=parsed.avg_power_w if parsed.avg_power_w is not None else prev.avg_power_w,
            calories_kcal=(
                parsed.total_energy_kcal
                if parsed.total_energy_kcal is not None
                else prev.calories_kcal
            ),
            heart_rate=parsed.heart_rate if parsed.heart_rate is not None else prev.heart_rate,
            elapsed_s=elapsed,
            remaining_s=parsed.remaining_s if parsed.remaining_s is not None else prev.remaining_s,
        )
        self._metrics = metrics
        self._update_aggregates(metrics)
        if timer_changed:
            await self.broadcast({"type": "status", "payload": self.status().model_dump()})
        await self.broadcast({"type": "metrics", "payload": metrics.model_dump()})

        now = time.monotonic()
        if now - self._last_sample_at >= SAMPLE_INTERVAL_SEC:
            self._last_sample_at = now
            self._persist_sample(metrics)

    def _update_aggregates(self, m: RowerMetrics) -> None:
        if m.stroke_rate is not None and m.stroke_rate > 0:
            self._spm_sum += m.stroke_rate
            self._spm_n += 1
        if m.pace_s is not None:
            self._pace_sum += m.pace_s
            self._pace_n += 1
        if m.power_w is not None:
            self._power_sum += m.power_w
            self._power_n += 1
            self._max_power = max(self._max_power, int(m.power_w))
        if m.heart_rate is not None:
            self._hr_sum += m.heart_rate
            self._hr_n += 1
            self._max_hr = max(self._max_hr, m.heart_rate)

    def _persist_sample(self, m: RowerMetrics) -> None:
        if not self._session_id or self._started_monotonic is None:
            return
        db = SessionLocal()
        try:
            sample = TelemetrySample(
                session_id=self._session_id,
                t_offset_s=time.monotonic() - self._started_monotonic,
                distance_m=m.distance_m,
                stroke_rate=m.stroke_rate,
                stroke_count=m.stroke_count,
                pace_s=m.pace_s,
                avg_intensity_mps=m.avg_intensity_mps,
                power_w=m.power_w,
                calories_kcal=m.calories_kcal,
                heart_rate=m.heart_rate,
                elapsed_s=m.elapsed_s,
            )
            db.add(sample)
            session = db.get(WorkoutSession, self._session_id)
            if session:
                if m.distance_m is not None:
                    session.distance_m = m.distance_m
                if m.stroke_count is not None:
                    session.stroke_count = m.stroke_count
                if m.calories_kcal is not None:
                    session.calories_kcal = m.calories_kcal
                if m.elapsed_s is not None:
                    session.duration_s = m.elapsed_s
                else:
                    session.duration_s = int(time.monotonic() - self._started_monotonic)
            db.commit()
        finally:
            db.close()

    async def _finalize_session(self) -> None:
        if self._session_id:
            db = SessionLocal()
            try:
                session = db.get(WorkoutSession, self._session_id)
                if session and session.ended_at is None:
                    session.ended_at = datetime.utcnow()
                    if self._metrics.distance_m is not None:
                        session.distance_m = self._metrics.distance_m
                    if self._metrics.stroke_count is not None:
                        session.stroke_count = self._metrics.stroke_count
                    if self._metrics.calories_kcal is not None:
                        session.calories_kcal = self._metrics.calories_kcal
                    session.duration_s = self._timer_elapsed_s()
                    session.avg_spm = self._spm_sum / self._spm_n if self._spm_n else None
                    session.avg_pace_s = self._pace_sum / self._pace_n if self._pace_n else None
                    session.avg_power_w = self._power_sum / self._power_n if self._power_n else None
                    session.avg_hr = self._hr_sum / self._hr_n if self._hr_n else None
                    session.max_hr = self._max_hr or None
                    session.max_power_w = self._max_power or None
                    db.commit()
            finally:
                db.close()

        self._connected = False
        self._source = None
        self._task = None
        self._reset_timer()
        self._user_max_hr = None
        self._message = "Workout beendet"
        await idle_inhibit.release()
        await self.broadcast({"type": "status", "payload": self.status().model_dump()})
        self._session_id = None
        self._user_id = None
        self._user_name = None
        self._mode = None


workout_manager = WorkoutManager()
