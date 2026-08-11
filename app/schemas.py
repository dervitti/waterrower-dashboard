from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sex: str | None = None
    birth_year: int | None = Field(default=None, ge=1920, le=2018)
    weight_kg: float | None = Field(default=None, gt=0, lt=400)
    max_hr: int | None = Field(default=None, ge=80, le=230)
    notes: str | None = None


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sex: str | None = None
    birth_year: int | None = Field(default=None, ge=1920, le=2018)
    weight_kg: float | None = Field(default=None, gt=0, lt=400)
    max_hr: int | None = Field(default=None, ge=80, le=230)
    notes: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sex: str | None = None
    birth_year: int | None = None
    weight_kg: float | None
    max_hr: int | None
    estimated_max_hr: int | None = None
    effective_max_hr: int | None = None
    hr_zones: list[dict] = Field(default_factory=list)
    notes: str | None
    created_at: datetime
    session_count: int = 0


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str | None = None
    started_at: datetime
    ended_at: datetime | None
    source: str
    distance_m: float
    duration_s: int
    stroke_count: int
    calories_kcal: float
    avg_spm: float | None
    avg_pace_s: float | None
    avg_power_w: float | None
    avg_hr: float | None
    max_hr: int | None
    max_power_w: int | None


class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    t_offset_s: float
    distance_m: float | None
    stroke_rate: float | None
    stroke_count: int | None
    pace_s: float | None
    avg_intensity_mps: float | None = None
    power_w: float | None
    calories_kcal: float | None
    heart_rate: int | None
    elapsed_s: int | None


class SessionDetail(SessionSummary):
    samples: list[SampleOut] = []


class RowerMetrics(BaseModel):
    stroke_rate: float | None = None
    stroke_count: int | None = None
    distance_m: float | None = None
    pace_s: float | None = None
    avg_pace_s: float | None = None
    avg_intensity_mps: float | None = None
    power_w: float | None = None
    avg_power_w: float | None = None
    calories_kcal: float | None = None
    heart_rate: int | None = None
    elapsed_s: int | None = None
    remaining_s: int | None = None


class WorkoutStartRequest(BaseModel):
    user_id: int
    mode: str = Field(default="ble", pattern="^(ble|demo|usb)$")
    device_address: str | None = None
    serial_port: str | None = None


class DeviceInfo(BaseModel):
    name: str | None
    address: str
    rssi: int | None = None


class WorkoutStatus(BaseModel):
    active: bool
    mode: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    user_max_hr: int | None = None
    session_id: int | None = None
    device_name: str | None = None
    connected: bool = False
    metrics: RowerMetrics | None = None
    message: str | None = None
    timer_running: bool = False
