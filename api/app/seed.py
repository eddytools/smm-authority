from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Role, User
from app.security import hash_password


def ensure_admin(db: Session, settings: Settings) -> None:
    """Create the bootstrap admin from env if missing. Never overwrites an existing account."""
    if not settings.admin_email or not settings.admin_password:
        return
    email = settings.admin_email.lower()
    if db.scalar(select(User).where(User.email == email)):
        return
    db.add(User(email=email, name="Admin", password_hash=hash_password(settings.admin_password), role=Role.admin))
    db.commit()
