from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import WorkoutSession
from app.schemas import SampleOut, SessionDetail, SessionSummary

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


def _summary(session: WorkoutSession, user_name: str | None = None) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        user_id=session.user_id,
        user_name=user_name or (session.user.name if session.user else None),
        started_at=session.started_at,
        ended_at=session.ended_at,
        source=session.source,
        distance_m=session.distance_m,
        duration_s=session.duration_s,
        stroke_count=session.stroke_count,
        calories_kcal=session.calories_kcal,
        avg_spm=session.avg_spm,
        avg_pace_s=session.avg_pace_s,
        avg_power_w=session.avg_power_w,
        avg_hr=session.avg_hr,
        max_hr=session.max_hr,
        max_power_w=session.max_power_w,
    )


@router.get("", response_model=list[SessionSummary])
def list_sessions(
    user_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[SessionSummary]:
    stmt = (
        select(WorkoutSession)
        .options(selectinload(WorkoutSession.user))
        .order_by(WorkoutSession.started_at.desc())
        .limit(limit)
    )
    if user_id is not None:
        stmt = stmt.where(WorkoutSession.user_id == user_id)
    sessions = db.scalars(stmt).all()
    return [_summary(s) for s in sessions]


@router.post("/bulk-delete")
def bulk_delete_sessions(payload: BulkDeleteRequest, db: Session = Depends(get_db)) -> dict:
    sessions = db.scalars(
        select(WorkoutSession).where(WorkoutSession.id.in_(payload.ids))
    ).all()
    deleted = 0
    for session in sessions:
        db.delete(session)
        deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: int, db: Session = Depends(get_db)) -> SessionDetail:
    session = db.scalar(
        select(WorkoutSession)
        .options(
            selectinload(WorkoutSession.user),
            selectinload(WorkoutSession.samples),
        )
        .where(WorkoutSession.id == session_id)
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    base = _summary(session)
    samples = [
        SampleOut.model_validate(s)
        for s in sorted(session.samples, key=lambda x: x.t_offset_s)
    ]
    return SessionDetail(**base.model_dump(), samples=samples)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, db: Session = Depends(get_db)) -> None:
    session = db.get(WorkoutSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    db.delete(session)
    db.commit()
