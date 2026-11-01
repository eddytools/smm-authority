from datetime import datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, select

from app.access import get_accessible_venture
from app.deps import CurrentUser, DbSession
from app.models import BriefVersion, Community, FeedItem, Influencer, ItemStatus, PlanSlot, Source, SourceType
from app.routers.communities import heat_report
from app.routers.influencers import influencer_digest
from app.routers.replies import find_opportunities
from app.today import OFF, coverage, day_bounds, source_health, suggestions, week_bounds, week_progress

router = APIRouter(prefix="/ventures/{venture_id}", tags=["today"])
SLOT_FIELDS = ("id", "scheduled_at", "platform", "post_type", "stage", "topic", "status", "locked")


def _slot(s: PlanSlot) -> dict:
    return {**{f: getattr(s, f) for f in SLOT_FIELDS}, "post_type": s.post_type.value, "stage": s.stage.value, "status": s.status.value, "has_draft": bool((s.draft or "").strip()), "will_auto_publish": s.will_auto_publish}


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/today")
def today(venture_id: int, user: CurrentUser, db: DbSession, tz: Annotated[str, Query(max_length=64)] = "UTC"):
    """One summary of today's research, what's trending, what influencers are writing, suggestions and the calendar.
    Deterministic: reads what the scheduled jobs already collected, calls no AI and no outside service."""
    venture = get_accessible_venture(db, venture_id, user)
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Unknown timezone")
    now = datetime.now(timezone.utc)
    day = timedelta(days=1)

    # --- fetched details: per-source health and counts -------------------------------------------------------
    sources = db.scalars(select(Source).where(Source.venture_id == venture_id).order_by(Source.id)).unique().all()
    by_source = {
        sid: (n24, n7)
        for sid, n24, n7 in db.execute(
            select(
                FeedItem.source_id,
                func.sum(case((FeedItem.fetched_at >= now - day, 1), else_=0)),
                func.count(),
            ).where(FeedItem.venture_id == venture_id, FeedItem.fetched_at >= now - 7 * day).group_by(FeedItem.source_id)
        )
    }
    last_pasted = dict(db.execute(select(FeedItem.source_id, func.max(FeedItem.fetched_at)).where(FeedItem.venture_id == venture_id).group_by(FeedItem.source_id)).all())
    src_rows, health = [], []
    for s in sources:
        manual = s.type == SourceType.manual  # nothing to fetch: you paste its posts in
        h = "paused" if not s.enabled else "manual" if manual else source_health(s.last_status, s.last_fetched_at, now)
        if s.enabled and not manual:
            health.append(h)
        n24, n7 = by_source.get(s.id, (0, 0))
        src_rows.append({
            "id": s.id, "type": s.type.value, "icon": s.influencer.platform if s.influencer else s.community.platform if s.community else s.type.value, "label": s.influencer.name if s.influencer else s.community.name if s.community else (s.label or s.target),
            "kind": "influencer" if s.influencer else "community" if s.community else "source", "enabled": s.enabled, "health": h, "error": s.last_error,
            "last_fetched_at": _aware(last_pasted.get(s.id) if manual else s.last_fetched_at), "new_24h": int(n24 or 0), "items_7d": int(n7 or 0),
        })
    fetched_times = [r["last_fetched_at"] for r in src_rows if r["last_fetched_at"] and r["enabled"] and r["health"] != "manual"]
    local_today = now.astimezone(zone).date()
    per_day = {local_today - timedelta(days=i): 0 for i in range(6, -1, -1)}
    for (fetched,) in db.execute(select(FeedItem.fetched_at).where(FeedItem.venture_id == venture_id, FeedItem.fetched_at >= now - 8 * day)):
        d = _aware(fetched).astimezone(zone).date()
        if d in per_day:
            per_day[d] += 1
    manual_24h = db.scalar(
        select(func.count()).select_from(FeedItem).join(Source, Source.id == FeedItem.source_id).where(FeedItem.venture_id == venture_id, Source.type == SourceType.manual, FeedItem.fetched_at >= now - day)
    )
    unreviewed = db.scalar(select(func.count()).select_from(FeedItem).where(FeedItem.venture_id == venture_id, FeedItem.status == ItemStatus.new))
    fetch = {
        "coverage": coverage(health),
        "items_24h": sum(r["new_24h"] for r in src_rows) + (manual_24h or 0),
        "items_7d": sum(r["items_7d"] for r in src_rows),
        "unreviewed": unreviewed,
        "last_fetched_at": max(fetched_times) if fetched_times else None,
        "by_day": [{"date": d.isoformat(), "items": n} for d, n in per_day.items()],
        "sources": src_rows,
    }

    # --- what's trending --------------------------------------------------------------------------------------
    top_items = db.scalars(
        select(FeedItem)
        .where(FeedItem.venture_id == venture_id, FeedItem.status != ItemStatus.dismissed, FeedItem.published_at >= now - 3 * day)
        .order_by(func.coalesce(FeedItem.relevance, FeedItem.rule_score).desc(), FeedItem.published_at.desc())
        .limit(6)
    ).unique().all()
    heat = heat_report(db, venture, 14)
    trending = {
        "items": [
            {"id": i.id, "title": i.title, "url": i.url, "source_type": i.source_type, "icon": i.icon_type, "source_label": i.source_label, "influencer": i.influencer_name, "engagement": i.engagement,
             "score": round(i.relevance if i.relevance is not None else i.rule_score), "ai_scored": i.relevance is not None, "why": i.why_it_matters, "published_at": _aware(i.published_at), "status": i.status.value}
            for i in top_items
        ],
        "topics": heat["topics"][:5],
        "heat_note": heat["note"],
    }

    # --- what influencers are writing -------------------------------------------------------------------------
    digest = influencer_digest(db, venture, 14)
    infs = db.scalars(select(Influencer).where(Influencer.venture_id == venture_id).order_by(Influencer.name)).all()
    people = []
    for inf in infs:
        if not inf.source.enabled:
            continue
        latest = db.scalars(select(FeedItem).where(FeedItem.source_id == inf.source_id).order_by(FeedItem.published_at.desc()).limit(1)).first()
        n7 = db.scalar(select(func.count()).select_from(FeedItem).where(FeedItem.source_id == inf.source_id, FeedItem.published_at >= now - 7 * day))
        people.append({
            "id": inf.id, "name": inf.name, "platform": inf.platform, "avatar_url": inf.avatar_url, "profile_url": inf.profile_url, "posts_7d": n7,
            "latest": {"title": latest.title, "url": latest.url, "engagement": latest.engagement, "published_at": _aware(latest.published_at)} if latest else None,
        })
    people.sort(key=lambda p: (p["latest"] is None, -(p["latest"]["published_at"].timestamp() if p["latest"] else 0), p["name"]))
    influencers = {"people": people[:8], "total": len(people), "topics": digest["topics"][:4], "note": digest["note"]}

    # --- calendar -----------------------------------------------------------------------------------------------
    start, end, dates = day_bounds(now, zone, 7)
    upcoming = db.scalars(select(PlanSlot).where(PlanSlot.venture_id == venture_id, PlanSlot.scheduled_at >= start, PlanSlot.scheduled_at < end, PlanSlot.status != "archived").order_by(PlanSlot.scheduled_at, PlanSlot.id)).unique().all()
    wstart, wend = week_bounds(now, zone)
    week_slots = db.scalars(select(PlanSlot).where(PlanSlot.venture_id == venture_id, PlanSlot.scheduled_at >= wstart, PlanSlot.scheduled_at < wend, PlanSlot.status != "archived")).unique().all()
    open_states = ("idea", "drafted", "in_review", "approved", "scheduled")
    late = db.scalars(select(PlanSlot).where(PlanSlot.venture_id == venture_id, PlanSlot.scheduled_at < now, PlanSlot.scheduled_at >= now - 14 * day, PlanSlot.status.in_(open_states)).order_by(PlanSlot.scheduled_at.desc()).limit(5)).unique().all()
    cal_days = [{"date": d.isoformat(), "is_today": d == dates[0], "slots": []} for d in dates]
    index = {d.isoformat(): c for d, c in zip(dates, cal_days)}
    for s in upcoming:
        index[_aware(s.scheduled_at).astimezone(zone).date().isoformat()]["slots"].append(_slot(s))
    calendar = {"days": cal_days, "week": week_progress([{"status": s.status.value} for s in week_slots]), "late": [_slot(s) for s in late], "total_upcoming": len(upcoming)}

    # --- suggestions --------------------------------------------------------------------------------------------
    used_items = set(db.scalars(select(PlanSlot.source_item_id).where(PlanSlot.venture_id == venture_id, PlanSlot.source_item_id.is_not(None))))
    saved = db.scalars(select(FeedItem).where(FeedItem.venture_id == venture_id, FeedItem.status == ItemStatus.saved).order_by(FeedItem.published_at.desc()).limit(10)).unique().all()
    soon = [s for s in upcoming if _aware(s.scheduled_at) <= now + 3 * day and s.status.value == "idea" and not (s.draft or "").strip()]
    opp = find_opportunities(db, venture, 2)
    has_brief = db.scalar(select(func.count()).select_from(BriefVersion).where(BriefVersion.venture_id == venture_id)) > 0
    setup = {
        "brief": has_brief, "sources": bool(sources) or bool(infs), "influencers": bool(infs),
        "plan": db.scalar(select(func.count()).select_from(PlanSlot).where(PlanSlot.venture_id == venture_id)) > 0,
    }
    tips = suggestions(
        topic_gaps=[t for t in digest["topics"] if not t["covered"]],
        heat_gaps=[t for t in heat["topics"] if not t["covered"] and t["in_niche"]],
        draft_slots=[{"topic": s.topic, "platform": s.platform, "when": _aware(s.scheduled_at).astimezone(zone).strftime("%a %H:%M")} for s in soon],
        opportunities=opp,
        saved_items=[{"title": i.title} for i in saved if i.id not in used_items],
        setup=setup,
    )
    return {"generated_at": now, "timezone": tz, "setup": setup, "fetch": fetch, "trending": trending, "influencers": influencers, "suggestions": tips, "calendar": calendar}
