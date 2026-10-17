"""Per-user daily AI budget shared by every on-demand AI endpoint (PRD R3)."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AIUsage, Role, User


def ensure_budget(db: Session, user: User, settings: Settings) -> None:
    if user.role == Role.admin:
        return
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    used = db.scalar(select(func.count()).select_from(AIUsage).where(AIUsage.user_id == user.id, AIUsage.created_at >= since))
    if used >= settings.ai_daily_limit_per_user:
        raise HTTPException(429, f"Daily AI limit reached ({settings.ai_daily_limit_per_user} requests). Try again tomorrow.")


def record_usage(db: Session, user: User, venture_id: int, feature: str, result) -> None:
    db.add(AIUsage(user_id=user.id, venture_id=venture_id, feature=feature, model=result.model, input_tokens=result.input_tokens, output_tokens=result.output_tokens))
