"""Parse Bluetooth FTMS Rower Data (characteristic 0x2AD1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedRowerData:
    stroke_rate: float | None = None
    stroke_count: int | None = None
    avg_stroke_rate: float | None = None
    distance_m: float | None = None
    pace_s: float | None = None
    avg_pace_s: float | None = None
    avg_intensity_mps: float | None = None  # S4 Average Intensity (m/s)
    power_w: float | None = None
    avg_power_w: float | None = None
    resistance: float | None = None
    total_energy_kcal: float | None = None
    energy_per_hour: float | None = None
    energy_per_minute: float | None = None
    heart_rate: int | None = None
    metabolic_equivalent: float | None = None
    elapsed_s: int | None = None
    remaining_s: int | None = None


def _u24(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)


def parse_rower_data(payload: bytes | bytearray) -> ParsedRowerData:
    """Decode FTMS Rower Data notification payload.

    Flag bit 0 ("More Data") is inverted for stroke fields:
    0 = Stroke Rate + Stroke Count present, 1 = absent.
    """
    if len(payload) < 2:
        return ParsedRowerData()

    flags = payload[0] | (payload[1] << 8)
    i = 2
    out = ParsedRowerData()

    more_data = bool(flags & 0x0001)
    if not more_data:
        if i + 3 <= len(payload):
            out.stroke_rate = payload[i] * 0.5
            out.stroke_count = payload[i + 1] | (payload[i + 2] << 8)
            i += 3

    if flags & 0x0002 and i + 1 <= len(payload):
        out.avg_stroke_rate = payload[i] * 0.5
        i += 1

    if flags & 0x0004 and i + 3 <= len(payload):
        out.distance_m = float(_u24(payload, i))
        i += 3

    if flags & 0x0008 and i + 2 <= len(payload):
        out.pace_s = float(payload[i] | (payload[i + 1] << 8))
        i += 2

    if flags & 0x0010 and i + 2 <= len(payload):
        out.avg_pace_s = float(payload[i] | (payload[i + 1] << 8))
        i += 2

    if flags & 0x0020 and i + 2 <= len(payload):
        out.power_w = float(int.from_bytes(payload[i : i + 2], "little", signed=True))
        i += 2

    if flags & 0x0040 and i + 2 <= len(payload):
        out.avg_power_w = float(int.from_bytes(payload[i : i + 2], "little", signed=True))
        i += 2

    if flags & 0x0080 and i + 2 <= len(payload):
        out.resistance = float(int.from_bytes(payload[i : i + 2], "little", signed=True))
        i += 2

    if flags & 0x0100 and i + 5 <= len(payload):
        out.total_energy_kcal = float(payload[i] | (payload[i + 1] << 8))
        out.energy_per_hour = float(payload[i + 2] | (payload[i + 3] << 8))
        out.energy_per_minute = float(payload[i + 4])
        i += 5

    if flags & 0x0200 and i + 1 <= len(payload):
        out.heart_rate = int(payload[i])
        i += 1

    if flags & 0x0400 and i + 1 <= len(payload):
        out.metabolic_equivalent = payload[i] * 0.1
        i += 1

    if flags & 0x0800 and i + 2 <= len(payload):
        out.elapsed_s = int(payload[i] | (payload[i + 1] << 8))
        i += 2

    if flags & 0x1000 and i + 2 <= len(payload):
        out.remaining_s = int(payload[i] | (payload[i + 1] << 8))

    return out
