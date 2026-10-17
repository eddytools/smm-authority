from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Role, User, Venture


def get_accessible_venture(db: Session, venture_id: int, user: User) -> Venture:
    """Owners see their own ventures, admins see all. Others get 404 so ids aren't probeable."""
    venture = db.get(Venture, venture_id)
    if venture is None or (venture.owner_id != user.id and user.role != Role.admin):
        raise HTTPException(404, "Venture not found")
    return venture
