from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.access import get_accessible_venture
from app.ai import AIError, AIProvider
from app.ai_budget import ensure_budget, record_usage
from app.deps import CurrentUser, DbSession, SettingsDep
from app.feed_schemas import (
    MAX_SOURCES_PER_VENTURE,
    FeedItemOut,
    FeedItemUpdate,
    RefreshOut,
    ScoreOut,
    SourceCreate,
    SourceOut,
    SourceRefreshResult,
    SourceUpdate,
)
from app.jobs.ingest import ingest_venture
from app.models import BriefVersion, FeedItem, ItemStatus, Source, SourceType

router = APIRouter(prefix="/ventures/{venture_id}", tags=["trend feed"])


def _get_source(db, venture_id: int, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.venture_id != venture_id or source.is_managed:  # influencer and community sources are managed with them
        raise HTTPException(404, "Source not found")
    return source


# --- sources ----------------------------------------------------------------

@router.get("/sources", response_model=list[SourceOut])
def list_sources(venture_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    return [src for src in db.scalars(select(Source).where(Source.venture_id == venture_id).order_by(Source.id)).unique().all() if not src.is_managed]


@router.post("/sources", response_model=SourceOut, status_code=201)
def add_source(venture_id: int, body: SourceCreate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    count = db.scalar(select(func.count()).select_from(Source).where(Source.venture_id == venture_id, Source.type != SourceType.manual))
    if count >= MAX_SOURCES_PER_VENTURE:
        raise HTTPException(400, f"A venture can have at most {MAX_SOURCES_PER_VENTURE} sources")
    source = Source(venture_id=venture_id, type=body.type, target=body.target, label=body.label)
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This source is already added")
    db.refresh(source)
    return source


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(venture_id: int, source_id: int, body: SourceUpdate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    source = _get_source(db, venture_id, source_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(venture_id: int, source_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    db.delete(_get_source(db, venture_id, source_id))
    db.commit()


# --- feed -------------------------------------------------------------------

@router.get("/feed", response_model=list[FeedItemOut])
def list_feed(
    venture_id: int,
    user: CurrentUser,
    db: DbSession,
    status: Literal["active", "new", "saved", "dismissed"] = "active",
    source_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Best first: AI relevance when the user asked for scoring, otherwise the deterministic rule score."""
    get_accessible_venture(db, venture_id, user)
    query = select(FeedItem).where(FeedItem.venture_id == venture_id)
    if status == "active":
        query = query.where(FeedItem.status != ItemStatus.dismissed)
    else:
        query = query.where(FeedItem.status == ItemStatus(status))
    if source_id is not None:
        query = query.where(FeedItem.source_id == source_id)
    query = query.order_by(func.coalesce(FeedItem.relevance, FeedItem.rule_score).desc(), FeedItem.published_at.desc(), FeedItem.id.desc())
    return db.scalars(query.limit(limit).offset(offset)).unique().all()


@router.patch("/feed/{item_id}", response_model=FeedItemOut)
def update_item(venture_id: int, item_id: int, body: FeedItemUpdate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    item = db.get(FeedItem, item_id)
    if item is None or item.venture_id != venture_id:
        raise HTTPException(404, "Feed item not found")
    item.status = ItemStatus(body.status)
    db.commit()
    db.refresh(item)
    return item


@router.post("/feed/refresh", response_model=RefreshOut)
def refresh(venture_id: int, request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep):
    """Run the same ingest script the scheduler runs, now, for this venture."""
    venture = get_accessible_venture(db, venture_id, user)
    last = db.scalar(select(func.max(Source.last_fetched_at)).where(Source.venture_id == venture_id))
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        wait = settings.refresh_min_interval_seconds - (datetime.now(timezone.utc) - last).total_seconds()
        if wait > 0:
            raise HTTPException(429, f"Refreshed moments ago. Try again in {int(wait) + 1}s.")
    report = ingest_venture(db, venture, request.app.state.fetcher, settings)
    return RefreshOut(
        new_items=report.new_items,
        sources=[SourceRefreshResult(source_id=s.source_id, status=s.status, new_items=s.new_items, error=s.error) for s in report.sources],
    )


@router.post("/feed/score", response_model=ScoreOut)
def score(venture_id: int, request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep):
    """On-demand AI relevance scoring of the best not-yet-scored items (shortlisted by the rule score)."""
    venture = get_accessible_venture(db, venture_id, user)
    ai: AIProvider | None = request.app.state.ai
    if ai is None:
        raise HTTPException(503, "AI scoring is not configured on this server")

    since = datetime.now(timezone.utc) - timedelta(days=14)
    items = db.scalars(
        select(FeedItem)
        .where(FeedItem.venture_id == venture_id, FeedItem.scored_at.is_(None), FeedItem.status != ItemStatus.dismissed, FeedItem.published_at >= since)
        .order_by(FeedItem.rule_score.desc(), FeedItem.id)
        .limit(settings.ai_score_batch)
    ).unique().all()
    if not items:
        return ScoreOut(scored=0)

    ensure_budget(db, user, settings)
    brief_row = db.scalar(select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1))
    brief = None
    if brief_row:
        d = brief_row.data
        brief = {
            "niche_statement": d["ideation"].get("niche_statement"),
            "pillars": d["ideation"].get("pillars", []),
            "icp": {k: d["icp"].get(k) for k in ("industry", "roles", "pains", "goals")},
            "offer": d["offer"].get("offer"),
        }
    payload = [{"id": i.id, "title": i.title, "summary": (i.summary or "")[:300], "source": i.source_label, "engagement": i.engagement} for i in items]
    try:
        result = ai.score_feed({"name": venture.name, "niche": venture.niche, "description": venture.description}, brief, payload)
    except AIError as exc:
        raise HTTPException(exc.status_code, exc.message)

    now = datetime.now(timezone.utc)
    for item in items:
        if item.id in result.scores:
            item.relevance, item.why_it_matters = result.scores[item.id]
            item.scored_at = now
    record_usage(db, user, venture.id, "feed_score", result)
    db.commit()
    return ScoreOut(scored=len(result.scores))
