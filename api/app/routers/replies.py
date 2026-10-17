from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access import get_accessible_venture
from app.ai import AIError, AIProvider
from app.ai_budget import ensure_budget, record_usage
from app.deps import CurrentUser, DbSession, SettingsDep
from app.feed_parsers import url_hash
from app.framework import PLATFORM_ALLOWED, STAGE_OF, SlotStatus
from app.jobs.scoring import brief_keywords
from app.models import BriefVersion, FeedItem, ItemStatus, PlanSlot, QuickReply
from app.replies import promo_terms, rank_opportunities, reply_context
from app.reply_schemas import OpportunityOut, RedraftRequest, ReplyOut, ReplyRequest, ReplyUpdate, ToPlanOut, ToPlanRequest

router = APIRouter(prefix="/ventures/{venture_id}/replies", tags=["quick replies"])


def _brief(db, venture_id: int) -> dict | None:
    row = db.scalar(select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1))
    return row.data if row else None


def _get(db, venture_id: int, reply_id: int) -> QuickReply:
    reply = db.get(QuickReply, reply_id)
    if reply is None or reply.venture_id != venture_id:
        raise HTTPException(404, "Reply not found")
    return reply


def _ai(request: Request) -> AIProvider:
    ai = request.app.state.ai
    if ai is None:
        raise HTTPException(503, "AI drafting is not configured on this server")
    return ai


def _venture_facts(venture) -> dict:
    return {"name": venture.name, "niche": venture.niche, "website": venture.website_url}


@router.get("/opportunities", response_model=list[OpportunityOut])
def opportunities(venture_id: int, user: CurrentUser, db: DbSession):
    """Questions worth answering, from the trend feed: question-like, recent, lively, close to your niche. Scripted, no AI."""
    venture = get_accessible_venture(db, venture_id, user)
    now = datetime.now(timezone.utc)
    done = {r for r in db.scalars(select(QuickReply.source_key).where(QuickReply.venture_id == venture_id, QuickReply.source_key.is_not(None)))}
    items = db.scalars(
        select(FeedItem)
        .where(FeedItem.venture_id == venture_id, FeedItem.status != ItemStatus.dismissed, FeedItem.published_at >= now - timedelta(days=3))
        .order_by(FeedItem.published_at.desc())
        .limit(300)
    ).unique().all()
    rows = [
        {"id": i.id, "title": i.title, "summary": i.summary, "url": i.url, "source_label": i.source_label, "source_type": i.source_type, "engagement": i.engagement,
         "published_at": i.published_at, "rule_score": i.rule_score}
        for i in items
        if i.url_hash not in done and url_hash(i.url) not in done
    ]
    return rank_opportunities(rows, now, brief_keywords(venture.name, venture.niche, _brief(db, venture_id)))


@router.post("/draft", response_model=ReplyOut, status_code=201)
def draft(venture_id: int, body: ReplyRequest, request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep):
    """Draft a reply to a thread. It is saved to your reply queue; nothing is ever posted for you."""
    venture = get_accessible_venture(db, venture_id, user)
    item = None
    if body.feed_item_id is not None:
        item = db.get(FeedItem, body.feed_item_id)
        if item is None or item.venture_id != venture_id:
            raise HTTPException(404, "Feed item not found")
    question = body.question_text or "\n\n".join(x for x in (item.title, item.summary) if x)
    if len(question.strip()) < 10:
        raise HTTPException(422, "Paste the question you want to reply to.")
    url = body.source_url or (item.url if item else None)
    community = body.community or (item.source.target if item and item.source.type.value == "reddit" else None)
    key = url_hash(url) if url else None
    if key:
        existing = db.scalar(select(QuickReply).where(QuickReply.venture_id == venture_id, QuickReply.source_key == key))
        if existing:  # one draft per thread: this is a help tool, not a way to flood a community
            raise HTTPException(409, f"You already drafted a reply for this thread (reply #{existing.id}). Open it from your queue instead.")

    ai = _ai(request)
    ensure_budget(db, user, settings)
    brief = _brief(db, venture_id)
    context = reply_context(_venture_facts(venture), brief, platform=body.platform, community=community, rules=body.community_rules, question=question, instructions=body.instructions, existing=None)
    try:
        result = ai.draft_reply(context)
    except AIError as exc:
        raise HTTPException(exc.status_code, exc.message)
    record_usage(db, user, venture.id, "reply_draft", result)
    reply = QuickReply(
        venture_id=venture_id, platform=body.platform, community=community, source_url=url, source_key=key, feed_item_id=item.id if item else None,
        question_text=question, community_rules=body.community_rules, reply_draft=result.reply, post_idea_title=result.post_idea_title, post_idea=result.post_idea,
        notes=result.notes, promo_terms=promo_terms(_venture_facts(venture), brief),
    )
    db.add(reply)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You already drafted a reply for this thread.")
    db.refresh(reply)
    return reply


@router.get("", response_model=list[ReplyOut])
def list_replies(venture_id: int, user: CurrentUser, db: DbSession, status: Literal["open", "posted", "dismissed"] = "open", limit: Annotated[int, Query(ge=1, le=200)] = 100):
    get_accessible_venture(db, venture_id, user)
    return db.scalars(select(QuickReply).where(QuickReply.venture_id == venture_id, QuickReply.status == status).order_by(QuickReply.created_at.desc(), QuickReply.id.desc()).limit(limit)).all()


@router.get("/{reply_id}", response_model=ReplyOut)
def get_reply(venture_id: int, reply_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    return _get(db, venture_id, reply_id)


@router.patch("/{reply_id}", response_model=ReplyOut)
def update_reply(venture_id: int, reply_id: int, body: ReplyUpdate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    reply = _get(db, venture_id, reply_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(reply, field, value)
    db.commit()
    db.refresh(reply)
    return reply


@router.post("/{reply_id}/redraft", response_model=ReplyOut)
def redraft(venture_id: int, reply_id: int, body: RedraftRequest, request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep):
    """Rewrite the reply (using the current text and any instructions). Replaces the saved draft, so the UI confirms first."""
    venture = get_accessible_venture(db, venture_id, user)
    reply = _get(db, venture_id, reply_id)
    if reply.status != "open":
        raise HTTPException(400, "Only open replies can be redrafted.")
    ai = _ai(request)
    ensure_budget(db, user, settings)
    brief = _brief(db, venture_id)
    context = reply_context(_venture_facts(venture), brief, platform=reply.platform, community=reply.community, rules=reply.community_rules, question=reply.question_text, instructions=body.instructions, existing=reply.reply_draft)
    try:
        result = ai.draft_reply(context)
    except AIError as exc:
        raise HTTPException(exc.status_code, exc.message)
    record_usage(db, user, venture.id, "reply_draft", result)
    reply.reply_draft, reply.notes = result.reply, result.notes
    if result.post_idea and not reply.post_idea:
        reply.post_idea_title, reply.post_idea = result.post_idea_title, result.post_idea
    reply.promo_terms = promo_terms(_venture_facts(venture), brief)
    db.commit()
    db.refresh(reply)
    return reply


@router.post("/{reply_id}/to-plan", response_model=ToPlanOut, status_code=201)
def to_plan(venture_id: int, reply_id: int, body: ToPlanRequest, user: CurrentUser, db: DbSession):
    """Turn the reply's post idea into a planned post on your own channel (an idea you edit, then approve like any other)."""
    get_accessible_venture(db, venture_id, user)
    reply = _get(db, venture_id, reply_id)
    if not reply.post_idea:
        raise HTTPException(400, "This reply has no post idea.")
    if reply.plan_slot_id and db.get(PlanSlot, reply.plan_slot_id):
        raise HTTPException(409, "This idea is already in your plan.")
    if body.post_type not in PLATFORM_ALLOWED[body.platform.value]:
        raise HTTPException(400, f"That post type doesn't fit {body.platform.value}.")
    topic = (reply.post_idea_title or reply.post_idea.split("\n")[0])[:300]
    slot = PlanSlot(
        venture_id=venture_id, scheduled_at=body.scheduled_at, platform=body.platform.value, post_type=body.post_type, stage=STAGE_OF[body.post_type],
        topic=topic, draft=reply.post_idea[:10000], status=SlotStatus.idea, locked=True,  # hand-made: regenerating a plan must not remove it
    )
    db.add(slot)
    db.flush()
    reply.plan_slot_id = slot.id
    db.commit()
    return ToPlanOut(slot_id=slot.id)


@router.delete("/{reply_id}", status_code=204)
def delete_reply(venture_id: int, reply_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    db.delete(_get(db, venture_id, reply_id))
    db.commit()
