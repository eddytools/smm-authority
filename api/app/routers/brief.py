from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access import get_accessible_venture
from app.ai import AIError, AIProvider
from app.ai_budget import ensure_budget, record_usage
from app.brief_schemas import BriefData, BriefOut, BriefSuggestion, BriefVersionSummary, SuggestRequest
from app.deps import CurrentUser, DbSession, SettingsDep
from app.models import BriefVersion

router = APIRouter(prefix="/ventures/{venture_id}/brief", tags=["authority brief"])


def _latest(db, venture_id: int) -> BriefVersion | None:
    return db.scalar(
        select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1)
    )


@router.get("", response_model=BriefOut | None)
def get_brief(venture_id: int, user: CurrentUser, db: DbSession):
    """Latest saved version, or null if the venture hasn't completed setup yet."""
    get_accessible_venture(db, venture_id, user)
    return _latest(db, venture_id)


@router.put("", response_model=BriefOut)
def save_brief(venture_id: int, body: BriefData, user: CurrentUser, db: DbSession):
    """Saving never edits history: it appends a new version (also how a rollback is done)."""
    get_accessible_venture(db, venture_id, user)
    for _ in range(2):
        latest = _latest(db, venture_id)
        brief = BriefVersion(
            venture_id=venture_id,
            version=(latest.version + 1) if latest else 1,
            data=body.model_dump(mode="json"),
            created_by_id=user.id,
        )
        db.add(brief)
        try:
            db.commit()
        except IntegrityError:  # two saves raced for the same version number
            db.rollback()
            continue
        db.refresh(brief)
        return brief
    raise HTTPException(409, "The brief was changed by someone else. Reload and try again.")


@router.get("/versions", response_model=list[BriefVersionSummary])
def list_versions(venture_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    return db.scalars(
        select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc())
    ).all()


@router.get("/versions/{version}", response_model=BriefOut)
def get_version(venture_id: int, version: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    brief = db.scalar(
        select(BriefVersion).where(BriefVersion.venture_id == venture_id, BriefVersion.version == version)
    )
    if brief is None:
        raise HTTPException(404, "Brief version not found")
    return brief


@router.post("/suggest", response_model=BriefSuggestion)
def suggest(venture_id: int, body: SuggestRequest, request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep):
    """On-demand AI draft of ideation + platform choice. Not saved: the user reviews, edits and saves it."""
    venture = get_accessible_venture(db, venture_id, user)
    ai: AIProvider | None = request.app.state.ai
    if ai is None:
        raise HTTPException(503, "AI suggestions are not configured on this server")

    ensure_budget(db, user, settings)

    try:
        result = ai.suggest_brief(
            {"name": venture.name, "niche": venture.niche, "description": venture.description, "website": venture.website_url},
            body,
        )
    except AIError as exc:
        raise HTTPException(exc.status_code, exc.message)

    record_usage(db, user, venture.id, "brief_suggest", result)
    db.commit()
    return BriefSuggestion(ideation=result.ideation, platforms=result.platforms, rationale=result.rationale)
