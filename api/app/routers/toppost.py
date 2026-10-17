from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.access import get_accessible_venture
from app.anatomy import build_analysis
from app.deps import CurrentUser, DbSession
from app.models import Community, FeedItem, Influencer, Source, SourceType

router = APIRouter(prefix="/ventures/{venture_id}", tags=["top posts"])


def _label(src: Source) -> str:
    if src.influencer is not None:
        return src.influencer.name
    if src.community is not None:
        return src.community.name
    return f"r/{src.target}"


@router.get("/top-posts")
def top_posts(venture_id: int, user: CurrentUser, db: DbSession, days: Annotated[int, Query(ge=14, le=180)] = 60):
    """Why the high-engagement posts you track are winning. Deterministic: no AI is involved.
    Uses posts from sources that expose engagement: subreddits, influencers and groups (not news/RSS feeds)."""
    get_accessible_venture(db, venture_id, user)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(FeedItem, Source)
        .join(Source, Source.id == FeedItem.source_id)
        .outerjoin(Influencer, Influencer.source_id == Source.id)
        .outerjoin(Community, Community.source_id == Source.id)
        .where(
            FeedItem.venture_id == venture_id,
            FeedItem.published_at >= since,
            Source.enabled.is_(True),
            or_(Source.type == SourceType.reddit, Influencer.id.is_not(None), Community.id.is_not(None)),
        )
    ).unique().all()
    posts = [
        {"community": _label(src), "title": it.title, "summary": it.summary, "url": it.url, "engagement": it.engagement, "published_at": it.published_at}
        for it, src in rows
    ]
    return build_analysis(posts, days)
