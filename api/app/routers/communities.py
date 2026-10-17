import secrets
import statistics
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.access import get_accessible_venture
from app.community_schemas import MAX_COMMUNITIES_PER_VENTURE, CommunityCreate, CommunityOut, CommunityPostCreate, CommunityUpdate
from app.deps import CurrentUser, DbSession
from app.feed_parsers import url_hash
from app.heat import build_heat
from app.influencer_schemas import PostOut
from app.jobs.scoring import brief_keywords, rule_score
from app.models import BriefVersion, Community, FeedItem, PlanSlot, Source, SourceType

router = APIRouter(prefix="/ventures/{venture_id}/communities", tags=["community heat"])
WINDOW = 30


def _get(db, venture_id: int, community_id: int) -> Community:
    c = db.get(Community, community_id)
    if c is None or c.venture_id != venture_id:
        raise HTTPException(404, "Community not found")
    return c


def _out(db, c: Community) -> CommunityOut:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW)
    rows = db.execute(select(FeedItem.engagement, FeedItem.published_at).where(FeedItem.source_id == c.source_id, FeedItem.published_at >= since)).all()
    last = db.scalar(select(func.max(FeedItem.published_at)).where(FeedItem.source_id == c.source_id))
    return CommunityOut(
        id=c.id, name=c.name, platform=c.platform, url=c.url, notes=c.notes, enabled=c.source.enabled, posts_30d=len(rows),
        median_engagement=statistics.median(r[0] for r in rows) if rows else None, last_post_at=last,
    )


def _brief(db, venture_id: int) -> dict | None:
    row = db.scalar(select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1))
    return row.data if row else None


@router.get("", response_model=list[CommunityOut])
def list_communities(venture_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    return [_out(db, c) for c in db.scalars(select(Community).where(Community.venture_id == venture_id).order_by(Community.name)).all()]


@router.post("", response_model=CommunityOut, status_code=201)
def add_community(venture_id: int, body: CommunityCreate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    if db.scalar(select(func.count()).select_from(Community).where(Community.venture_id == venture_id)) >= MAX_COMMUNITIES_PER_VENTURE:
        raise HTTPException(400, f"You can track at most {MAX_COMMUNITIES_PER_VENTURE} communities per venture")
    source = Source(venture_id=venture_id, type=SourceType.manual, target=f"community:{secrets.token_hex(6)}", label=body.name)
    c = Community(venture_id=venture_id, name=body.name, platform=body.platform, url=body.url, notes=body.notes, source=source)
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already track a community with that name")
    db.refresh(c)
    return _out(db, c)


@router.get("/heat")
def heat(venture_id: int, user: CurrentUser, db: DbSession, days: Annotated[int, Query(ge=7, le=60)] = 14):
    """What's hot in your communities (subreddits you follow plus groups you paste into). Deterministic: no AI is involved."""
    venture = get_accessible_venture(db, venture_id, user)
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(FeedItem, Source)
        .join(Source, Source.id == FeedItem.source_id)
        .outerjoin(Community, Community.source_id == Source.id)
        .where(
            FeedItem.venture_id == venture_id,
            FeedItem.published_at >= now - timedelta(days=2 * days),
            Source.enabled.is_(True),
            or_(Source.type == SourceType.reddit, Community.id.is_not(None)),
        )
    ).unique().all()
    posts = [
        {"community": (f"r/{src.target}" if src.type == SourceType.reddit else src.community.name), "title": it.title, "summary": it.summary, "url": it.url,
         "engagement": it.engagement, "published_at": it.published_at}
        for it, src in rows
    ]
    slots = db.scalars(select(PlanSlot).where(PlanSlot.venture_id == venture_id, PlanSlot.scheduled_at >= now - timedelta(days=60), PlanSlot.status != "skipped")).unique().all()
    own = [t for s in slots for t in (s.topic, s.draft)]
    return build_heat(posts, own, brief_keywords(venture.name, venture.niche, _brief(db, venture_id)), now, days)


@router.patch("/{community_id}", response_model=CommunityOut)
def update_community(venture_id: int, community_id: int, body: CommunityUpdate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    c = _get(db, venture_id, community_id)
    data = body.model_dump(exclude_unset=True)
    if "enabled" in data:
        c.source.enabled = data.pop("enabled")
    for field, value in data.items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return _out(db, c)


@router.delete("/{community_id}", status_code=204)
def delete_community(venture_id: int, community_id: int, user: CurrentUser, db: DbSession):
    """Also removes the posts you pasted for it (including any you saved)."""
    get_accessible_venture(db, venture_id, user)
    db.delete(_get(db, venture_id, community_id).source)
    db.commit()


@router.post("/{community_id}/posts", response_model=PostOut, status_code=201)
def add_post(venture_id: int, community_id: int, body: CommunityPostCreate, user: CurrentUser, db: DbSession):
    """Paste in a post you saw in the group, with its likes and comments. It joins the trend feed like any other item."""
    venture = get_accessible_venture(db, venture_id, user)
    c = _get(db, venture_id, community_id)
    now = datetime.now(timezone.utc)
    posted = body.posted_at or now
    first_line = next((ln.strip() for ln in body.text.splitlines() if ln.strip()), body.text)
    title = first_line if len(first_line) <= 300 else first_line[:297] + "…"
    engagement = body.likes + body.comments
    kws = brief_keywords(venture.name, venture.niche, _brief(db, venture_id))
    item = FeedItem(
        venture_id=venture_id, source_id=c.source_id, url=body.url, url_hash=url_hash(body.url), title=title, summary=body.text, author=None,
        published_at=posted, fetched_at=now, engagement=engagement, rule_score=rule_score(title, body.text, posted, engagement, kws, now),
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That post is already in your feed")
    db.refresh(item)
    return item
