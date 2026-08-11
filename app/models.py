from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    sex: Mapped[str | None] = mapped_column(String(8), nullable=True)  # m | f
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)  # manueller Override
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sessions: Mapped[list["WorkoutSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class WorkoutSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="ble")  # ble | demo

    distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    stroke_count: Mapped[int] = mapped_column(Integer, default=0)
    calories_kcal: Mapped[float] = mapped_column(Float, default=0.0)
    avg_spm: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_pace_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_power_w: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")
    samples: Mapped[list["TelemetrySample"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class TelemetrySample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), nullable=False, index=True
    )
    t_offset_s: Mapped[float] = mapped_column(Float, nullable=False)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    stroke_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    stroke_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pace_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_intensity_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped["WorkoutSession"] = relationship(back_populates="samples")
