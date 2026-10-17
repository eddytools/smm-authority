from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, DbSession, SettingsDep
from app.models import Role, User
from app.schemas import LoginRequest, RegisterRequest, Token, UserOut
from app.security import burn_verify, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: DbSession, settings: SettingsDep):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is disabled")
    # Self-registration always yields the "user" role; admins are bootstrapped or promoted by an admin.
    user = User(email=body.email, name=body.name, password_hash=hash_password(body.password), role=Role.user)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered")
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(body: LoginRequest, db: DbSession, settings: SettingsDep):
    invalid = HTTPException(401, "Invalid email or password")
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        burn_verify(body.password)
        raise invalid
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        raise invalid
    return Token(access_token=create_access_token(user.id, settings))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
