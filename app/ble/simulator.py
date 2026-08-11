"""Demo rower telemetry for development without hardware."""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable

from app.ble.parser import ParsedRowerData

MetricsCallback = Callable[[ParsedRowerData], Awaitable[None] | None]
StatusCallback = Callable[[str], Awaitable[None] | None]


class DemoRower:
    def __init__(
        self,
        on_metrics: MetricsCallback,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._on_metrics = on_metrics
        self._on_status = on_status
        self._stop = asyncio.Event()
        self.device_name = "Demo WaterRower"
        self.connected = False

    async def _emit_status(self, message: str) -> None:
        if self._on_status:
            result = self._on_status(message)
            if asyncio.iscoroutine(result):
                await result

    async def run(self) -> None:
        self.connected = True
        await self._emit_status("Demo-Modus gestartet")
        t = 0.0
        stroke_count = 0
        distance = 0.0
        calories = 0.0
        base_spm = 24.0
        base_power = 160.0
        base_hr = 128

        while not self._stop.is_set():
            wave = math.sin(t / 18.0)
            spm = base_spm + wave * 3 + random.uniform(-0.4, 0.4)
            power = base_power + wave * 35 + random.uniform(-8, 8)
            # rough pace from power (seconds / 500m)
            pace = max(90.0, 210.0 - power * 0.35 + random.uniform(-1.5, 1.5))
            speed_m_s = 500.0 / pace
            distance += speed_m_s
            stroke_count = int(t * spm / 60.0)
            calories += power * 0.0011
            hr = int(base_hr + wave * 12 + random.uniform(-2, 2))

            metrics = ParsedRowerData(
                stroke_rate=round(spm, 1),
                stroke_count=stroke_count,
                distance_m=round(distance, 1),
                pace_s=round(pace, 1),
                avg_pace_s=round(pace + 2, 1),
                power_w=round(power, 1),
                avg_power_w=round(base_power + wave * 10, 1),
                total_energy_kcal=round(calories, 1),
                heart_rate=hr,
                elapsed_s=int(t),
            )
            result = self._on_metrics(metrics)
            if asyncio.iscoroutine(result):
                await result

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            t += 1.0

        self.connected = False
        await self._emit_status("Demo-Modus gestoppt")

    async def stop(self) -> None:
        self._stop.set()
