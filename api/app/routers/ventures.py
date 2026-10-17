from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DbSession
from app.models import Role, User, Venture
from app.schemas import VentureCreate, VentureOut, VentureUpdate

router = APIRouter(prefix="/ventures", tags=["ventures"])

_DUPLICATE = "You already have a venture with this name"


def _get_accessible(db: Session, venture_id: int, user: User) -> Venture:
    """Owners see their own ventures, admins see all. Others get 404 so ids aren't probeable."""
    venture = db.get(Venture, venture_id)
    if venture is None or (venture.owner_id != user.id and user.role != Role.admin):
        raise HTTPException(404, "Venture not found")
    return venture


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, _DUPLICATE)


@router.get("", response_model=list[VentureOut])
def list_ventures(
    user: CurrentUser,
    db: DbSession,
    scope: Literal["mine", "all"] = "mine",
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if scope == "all" and user.role != Role.admin:
        raise HTTPException(403, "Admin access required")
    query = select(Venture).order_by(Venture.created_at.desc(), Venture.id.desc())
    if scope == "mine":
        query = query.where(Venture.owner_id == user.id)
    if not include_archived:
        query = query.where(Venture.is_archived.is_(False))
    return db.scalars(query.limit(limit).offset(offset)).unique().all()


@router.post("", response_model=VentureOut, status_code=201)
def create_venture(body: VentureCreate, user: CurrentUser, db: DbSession):
    venture = Venture(owner_id=user.id, **body.model_dump())
    db.add(venture)
    _commit(db)
    db.refresh(venture)
    return venture


@router.get("/{venture_id}", response_model=VentureOut)
def get_venture(venture_id: int, user: CurrentUser, db: DbSession):
    return _get_accessible(db, venture_id, user)


@router.patch("/{venture_id}", response_model=VentureOut)
def update_venture(venture_id: int, body: VentureUpdate, user: CurrentUser, db: DbSession):
    venture = _get_accessible(db, venture_id, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(venture, field, value)
    _commit(db)
    db.refresh(venture)
    return venture


@router.delete("/{venture_id}", status_code=204)
def delete_venture(venture_id: int, user: CurrentUser, db: DbSession):
    venture = _get_accessible(db, venture_id, user)
    db.delete(venture)
    db.commit()
