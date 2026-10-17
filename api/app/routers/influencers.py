import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.access import get_accessible_venture
from app.deps import CurrentUser, DbSession
from app.feed_parsers import url_hash
from app.influence import build_digest
from app.influencer_schemas import MAX_INFLUENCERS_PER_VENTURE, InfluencerCreate, InfluencerOut, InfluencerUpdate, PostCreate, PostOut
from app.jobs.scoring import brief_keywords, rule_score
from app.models import BriefVersion, FeedItem, Influencer, PlanSlot, Source, SourceType

router = APIRouter(prefix="/ventures/{venture_id}/influencers", tags=["influencer watch"])
WINDOW = 30  # days of posts behind the per-influencer numbers


def _get(db, venture_id: int, influencer_id: int) -> Influencer:
    inf = db.get(Influencer, influencer_id)
    if inf is None or inf.venture_id != venture_id:
        raise HTTPException(404, "Influencer not found")
    return inf


def _out(db, inf: Influencer) -> InfluencerOut:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW)
    count, avg = db.execute(
        select(func.count(), func.avg(FeedItem.engagement)).where(FeedItem.source_id == inf.source_id, FeedItem.published_at >= since)
    ).one()
    last = db.scalar(select(func.max(FeedItem.published_at)).where(FeedItem.source_id == inf.source_id))
    src = inf.source
    return InfluencerOut(
        id=inf.id, name=inf.name, platform=inf.platform, profile_url=inf.profile_url, notes=inf.notes, source_id=src.id,
        feed_url=src.target if src.type == SourceType.rss else None, enabled=src.enabled,
        posts_30d=count, avg_engagement=round(float(avg), 1) if avg is not None else None, last_post_at=last,
        last_status=src.last_status, last_error=src.last_error,
    )


def _brief(db, venture_id: int) -> dict | None:
    row = db.scalar(select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1))
    return row.data if row else None


@router.get("", response_model=list[InfluencerOut])
def list_influencers(venture_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    rows = db.scalars(select(Influencer).where(Influencer.venture_id == venture_id).order_by(Influencer.name)).all()
    return [_out(db, i) for i in rows]


@router.post("", response_model=InfluencerOut, status_code=201)
def add_influencer(venture_id: int, body: InfluencerCreate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    if db.scalar(select(func.count()).select_from(Influencer).where(Influencer.venture_id == venture_id)) >= MAX_INFLUENCERS_PER_VENTURE:
        raise HTTPException(400, f"You can follow at most {MAX_INFLUENCERS_PER_VENTURE} influencers per venture")
    if body.feed_url:
        source = Source(venture_id=venture_id, type=SourceType.rss, target=body.feed_url, label=body.name)
    else:
        source = Source(venture_id=venture_id, type=SourceType.manual, target=f"influencer:{secrets.token_hex(6)}", label=body.name)
    inf = Influencer(venture_id=venture_id, name=body.name, platform=body.platform, profile_url=body.profile_url, notes=body.notes, source=source)
    db.add(inf)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        taken = db.scalar(select(func.count()).select_from(Influencer).where(Influencer.venture_id == venture_id, Influencer.name == body.name))
        raise HTTPException(409, "You already follow someone with that name" if taken else "That feed is already one of your sources")
    db.refresh(inf)
    return _out(db, inf)


@router.get("/digest")
def digest(venture_id: int, user: CurrentUser, db: DbSession, days: Annotated[int, Query(ge=7, le=90)] = 14):
    """What the people you follow are talking about. Deterministic: no AI is involved."""
    venture = get_accessible_venture(db, venture_id, user)
    now = datetime.now(timezone.utc)
    items = db.execute(
        select(FeedItem, Influencer)
        .join(Influencer, Influencer.source_id == FeedItem.source_id)
        .where(FeedItem.venture_id == venture_id, FeedItem.published_at >= now - timedelta(days=days))
    ).all()
    enabled = {i.id for i in db.scalars(select(Influencer).where(Influencer.venture_id == venture_id)).all() if i.source.enabled}
    posts = [
        {"influencer_id": inf.id, "influencer": inf.name, "title": it.title, "summary": it.summary, "url": it.url, "engagement": it.engagement, "published_at": it.published_at}
        for it, inf in items
        if inf.id in enabled
    ]
    slots = db.scalars(select(PlanSlot).where(PlanSlot.venture_id == venture_id, PlanSlot.scheduled_at >= now - timedelta(days=60), PlanSlot.status != "skipped")).unique().all()
    own = [t for s in slots for t in (s.topic, s.draft)]
    niche = brief_keywords(venture.name, venture.niche, _brief(db, venture_id))
    return build_digest(posts, own, niche, now, days)


@router.patch("/{influencer_id}", response_model=InfluencerOut)
def update_influencer(venture_id: int, influencer_id: int, body: InfluencerUpdate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    inf = _get(db, venture_id, influencer_id)
    data = body.model_dump(exclude_unset=True)
    if "enabled" in data:
        inf.source.enabled = data.pop("enabled")
    if "name" in data:
        inf.source.label = data["name"]
    for field, value in data.items():
        setattr(inf, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already follow someone with that name")
    db.refresh(inf)
    return _out(db, inf)


@router.delete("/{influencer_id}", status_code=204)
def delete_influencer(venture_id: int, influencer_id: int, user: CurrentUser, db: DbSession):
    """Also removes their collected posts from your feed (including any you saved)."""
    get_accessible_venture(db, venture_id, user)
    db.delete(_get(db, venture_id, influencer_id).source)
    db.commit()


@router.post("/{influencer_id}/posts", response_model=PostOut, status_code=201)
def add_post(venture_id: int, influencer_id: int, body: PostCreate, user: CurrentUser, db: DbSession):
    """Paste in a post you saw (LinkedIn and X can't be read automatically). It joins the trend feed like any other item."""
    venture = get_accessible_venture(db, venture_id, user)
    inf = _get(db, venture_id, influencer_id)
    now = datetime.now(timezone.utc)
    posted = body.posted_at or now
    first_line = next((ln.strip() for ln in body.text.splitlines() if ln.strip()), body.text)
    title = first_line if len(first_line) <= 300 else first_line[:297] + "…"
    kws = brief_keywords(venture.name, venture.niche, _brief(db, venture_id))
    item = FeedItem(
        venture_id=venture_id, source_id=inf.source_id, url=body.url, url_hash=url_hash(body.url), title=title, summary=body.text,
        author=inf.name, published_at=posted, fetched_at=now, engagement=body.engagement,
        rule_score=rule_score(title, body.text, posted, body.engagement, kws, now),
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That post is already in your feed")
    db.refresh(item)
    return item
