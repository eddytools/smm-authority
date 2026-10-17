from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import AdminUser, DbSession
from app.models import Role, User
from app.schemas import AdminUserCreate, UserOut, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["users (admin)"])


@router.get("", response_model=list[UserOut])
def list_users(
    admin: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return db.scalars(select(User).order_by(User.id).limit(limit).offset(offset)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: AdminUserCreate, admin: AdminUser, db: DbSession):
    user = User(email=body.email, name=body.name, password_hash=hash_password(body.password), role=body.role)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered")
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, admin: AdminUser, db: DbSession):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, admin: AdminUser, db: DbSession):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    changes = body.model_dump(exclude_none=True)
    # Guarantees at least one active admin always remains: an admin cannot lock themselves out.
    if user.id == admin.id and (changes.get("role", Role.admin) != Role.admin or changes.get("is_active", True) is False):
        raise HTTPException(400, "You cannot demote or deactivate your own account")
    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
