"""Herzfrequenz: HFmax-Schätzung und Trainingszonen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HrZone:
    key: str
    name: str
    pct_lo: float
    pct_hi: float
    color: str


# Standard-5-Zonen-Modell (Prozent der HFmax)
HR_ZONES: tuple[HrZone, ...] = (
    HrZone("health", "Gesundheits-Zone", 0.50, 0.60, "#5ecf8a"),
    HrZone("metab", "Stoffwechsel-Zone", 0.60, 0.70, "#a8d94a"),
    HrZone("aero", "Aerobe Zone", 0.70, 0.80, "#f0b429"),
    HrZone("anaero", "Anaerobe Zone", 0.80, 0.90, "#f07838"),
    HrZone("race", "Wettkampf-Zone", 0.90, 1.00, "#ff2a3c"),
)


def age_from_birth_year(birth_year: int | None, today: date | None = None) -> int | None:
    if birth_year is None:
        return None
    today = today or date.today()
    age = today.year - int(birth_year)
    if age < 5 or age > 110:
        return None
    return age


def estimate_max_hr(
    *,
    sex: str | None,
    age: int | None,
    weight_kg: float | None,
) -> int | None:
    """Schätzt HFmax aus Geschlecht, Alter und Gewicht.

    Formel (gängige Sportmedizin-/Fitness-Rechner):
      HFmax = 210 − 0,5·Alter − 0,05·Gewicht_kg  [+ 4 bei Männern]

    Ohne Alter keine Schätzung. Fehlendes Gewicht → Referenz 75 kg (m) / 60 kg (w).
    """
    if age is None or age < 10 or age > 100:
        return None
    s = (sex or "m").strip().lower()
    female = s in {"f", "w", "female", "w", "weiblich", "frau"}
    if weight_kg is None or weight_kg <= 0:
        weight_kg = 60.0 if female else 75.0
    hr = 210.0 - 0.5 * float(age) - 0.05 * float(weight_kg)
    if not female:
        hr += 4.0
    return int(round(max(120, min(220, hr))))


def effective_max_hr(
    *,
    max_hr_override: int | None,
    sex: str | None,
    birth_year: int | None,
    weight_kg: float | None,
) -> int | None:
    if max_hr_override is not None and 80 <= max_hr_override <= 230:
        return int(max_hr_override)
    age = age_from_birth_year(birth_year)
    return estimate_max_hr(sex=sex, age=age, weight_kg=weight_kg)


def zone_bounds(max_hr: int) -> list[dict]:
    """Zonen mit absoluten BPM-Grenzen für die UI."""
    out: list[dict] = []
    for z in HR_ZONES:
        lo = int(round(max_hr * z.pct_lo))
        hi = int(round(max_hr * z.pct_hi))
        out.append(
            {
                "key": z.key,
                "name": z.name,
                "pct_lo": int(z.pct_lo * 100),
                "pct_hi": int(z.pct_hi * 100),
                "bpm_lo": lo,
                "bpm_hi": hi,
                "color": z.color,
            }
        )
    return out


def zone_for_hr(hr: int | None, max_hr: int | None) -> dict | None:
    if hr is None or max_hr is None or max_hr <= 0:
        return None
    pct = hr / max_hr
    if pct < 0.50:
        return {
            "key": "warmup",
            "name": "Aufwärmen / Erholung",
            "pct_lo": 0,
            "pct_hi": 50,
            "color": "#6a8a9a",
            "pct": round(pct * 100, 1),
        }
    for z in HR_ZONES:
        # oberes Intervall inklusiv nur bei letzter Zone
        if z.pct_lo <= pct < z.pct_hi or (z.key == "race" and pct >= z.pct_lo):
            return {
                "key": z.key,
                "name": z.name,
                "pct_lo": int(z.pct_lo * 100),
                "pct_hi": int(z.pct_hi * 100),
                "color": z.color,
                "pct": round(pct * 100, 1),
            }
    # > 100 %
    z = HR_ZONES[-1]
    return {
        "key": z.key,
        "name": z.name,
        "pct_lo": 90,
        "pct_hi": 100,
        "color": z.color,
        "pct": round(pct * 100, 1),
    }
