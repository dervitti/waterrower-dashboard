from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.hr_zones import age_from_birth_year, effective_max_hr, estimate_max_hr, zone_bounds
from app.models import User, WorkoutSession
from app.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def _norm_sex(sex: str | None) -> str | None:
    if not sex:
        return None
    s = sex.strip().lower()
    if s in {"m", "male", "mann", "männlich"}:
        return "m"
    if s in {"f", "w", "female", "frau", "weiblich"}:
        return "f"
    return None


def _to_out(user: User, session_count: int = 0) -> UserOut:
    age = age_from_birth_year(user.birth_year)
    estimated = estimate_max_hr(sex=user.sex, age=age, weight_kg=user.weight_kg)
    effective = effective_max_hr(
        max_hr_override=user.max_hr,
        sex=user.sex,
        birth_year=user.birth_year,
        weight_kg=user.weight_kg,
    )
    zones = zone_bounds(effective) if effective else []
    return UserOut(
        id=user.id,
        name=user.name,
        sex=user.sex,
        birth_year=user.birth_year,
        weight_kg=user.weight_kg,
        max_hr=user.max_hr,
        estimated_max_hr=estimated,
        effective_max_hr=effective,
        hr_zones=zones,
        notes=user.notes,
        created_at=user.created_at,
        session_count=session_count,
    )


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    rows = db.execute(
        select(User, func.count(WorkoutSession.id))
        .outerjoin(WorkoutSession, WorkoutSession.user_id == User.id)
        .group_by(User.id)
        .order_by(User.name)
    ).all()
    return [_to_out(user, count) for user, count in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserOut:
    existing = db.scalar(select(User).where(User.name == payload.name.strip()))
    if existing:
        raise HTTPException(status_code=409, detail="Name bereits vergeben")
    user = User(
        name=payload.name.strip(),
        sex=_norm_sex(payload.sex),
        birth_year=payload.birth_year,
        weight_kg=payload.weight_kg,
        max_hr=payload.max_hr,
        notes=payload.notes,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)) -> UserOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
        clash = db.scalar(select(User).where(User.name == data["name"], User.id != user_id))
        if clash:
            raise HTTPException(status_code=409, detail="Name bereits vergeben")
    if "sex" in data:
        data["sex"] = _norm_sex(data["sex"])
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    count = db.scalar(
        select(func.count()).select_from(WorkoutSession).where(WorkoutSession.user_id == user.id)
    )
    return _to_out(user, count or 0)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db)) -> None:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    db.delete(user)
    db.commit()
