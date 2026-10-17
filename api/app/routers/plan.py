from datetime import datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime
from sqlalchemy import func, select

from app.access import get_accessible_venture
from app.ai import AIError, AIProvider
from app.ai_budget import ensure_budget, record_usage
from app.deps import CurrentUser, DbSession, SettingsDep
from app.drafting import build_context, check_draft, placeholders
from app.framework import (
    DRAFT_REQUIRED,
    GUIDANCE,
    LABEL,
    PLATFORM_ALLOWED,
    READ_ONLY,
    ROTATION,
    STAGE_GOAL,
    STAGE_OF,
    TRANSITIONS,
    SlotStatus,
    Stage,
)
from app.models import BriefVersion, FeedItem, ItemStatus, PlanSlot
from app.plan_schemas import DraftOut, DraftRequest, GenerateOut, GenerateRequest, SlotCreate, SlotOut, SlotUpdate
from app.planner import Candidate, PlanningError, generate

router = APIRouter(prefix="/ventures/{venture_id}/plan", tags=["content planner"])
framework_router = APIRouter(prefix="/planner", tags=["content planner"])
CONTENT_FIELDS = {"scheduled_at", "platform", "post_type", "topic", "pillar", "cta", "draft"}
APPROVAL_STATUSES = {SlotStatus.approved, SlotStatus.scheduled, SlotStatus.published, SlotStatus.analysed}


@framework_router.get("/framework")
def framework(_user: CurrentUser):
    """Stages, post types, platform rules and the status pipeline, so the UI never hard-codes them."""
    return {
        "stages": [
            {
                "key": stage.value,
                "goal": STAGE_GOAL[stage],
                "post_types": [
                    {"key": t.value, "label": LABEL[t], "guidance": GUIDANCE[t], "platforms": sorted(p for p, ok in PLATFORM_ALLOWED.items() if t in ok)}
                    for t in ROTATION[stage]
                ],
            }
            for stage in Stage
        ],
        "statuses": [s.value for s in SlotStatus],
        "transitions": {s.value: sorted(x.value for x in nxt) for s, nxt in TRANSITIONS.items()},
    }


def _get_slot(db, venture_id: int, slot_id: int) -> PlanSlot:
    slot = db.get(PlanSlot, slot_id)
    if slot is None or slot.venture_id != venture_id:
        raise HTTPException(404, "Slot not found")
    return slot


def _check_fit(platform: str, post_type) -> None:
    if post_type not in PLATFORM_ALLOWED[platform]:
        raise HTTPException(400, f"{LABEL[post_type]} posts don't fit {platform}")


@router.post("/generate", response_model=GenerateOut)
def generate_plan(venture_id: int, body: GenerateRequest, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    brief_row = db.scalar(select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1))
    if brief_row is None or not brief_row.data.get("platforms"):
        raise HTTPException(400, "Choose at least one platform in the Authority setup first.")

    tz = ZoneInfo(body.timezone)
    weeks = 1 if body.period == "week" else 4
    range_start = datetime.combine(body.start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    range_end = datetime.combine(body.start_date + timedelta(days=7 * weeks), time.min, tzinfo=tz).astimezone(timezone.utc)

    in_range = select(PlanSlot).where(
        PlanSlot.venture_id == venture_id, PlanSlot.scheduled_at >= range_start, PlanSlot.scheduled_at < range_end, PlanSlot.status != SlotStatus.archived
    )
    existing = db.scalars(in_range).all()
    if existing and not body.replace:
        raise HTTPException(409, f"{len(existing)} posts are already planned in this period. Confirm to replace the unedited ones.")

    removable = [s for s in existing if s.status == SlotStatus.idea and not s.locked]
    for s in removable:
        db.delete(s)
    db.flush()
    kept = [s for s in existing if s not in removable]
    skip = {(s.platform, s.scheduled_at.astimezone(tz).date()) for s in kept}

    used = set(db.scalars(select(PlanSlot.source_item_id).where(PlanSlot.venture_id == venture_id, PlanSlot.source_item_id.is_not(None))))
    fresh = datetime.now(timezone.utc) - timedelta(days=14)
    items = db.scalars(
        select(FeedItem)
        .where(FeedItem.venture_id == venture_id, FeedItem.status != ItemStatus.dismissed, (FeedItem.status == ItemStatus.saved) | (FeedItem.published_at >= fresh))
        .order_by(func.coalesce(FeedItem.relevance, FeedItem.rule_score).desc())
        .limit(60)
    ).unique().all()
    candidates = [Candidate(i.id, i.title, i.relevance if i.relevance is not None else i.rule_score, i.status == ItemStatus.saved) for i in items if i.id not in used]

    try:
        planned = generate(brief_row.data, body.start_date, weeks, tz, body.mix.model_dump(), candidates, skip)
    except PlanningError as exc:
        raise HTTPException(400, str(exc))

    for p in planned:
        db.add(
            PlanSlot(
                venture_id=venture_id,
                scheduled_at=p.scheduled_at,
                platform=p.platform,
                post_type=p.post_type,
                stage=p.stage,
                pillar=p.pillar,
                topic=p.topic,
                cta=p.cta,
                reactive=p.reactive,
                source_item_id=p.source_item_id,
            )
        )
    db.commit()
    by_stage = {s.value: sum(p.stage == s for p in planned) for s in Stage}
    return GenerateOut(created=len(planned), removed=len(removable), kept=len(kept), by_stage=by_stage)


@router.get("", response_model=list[SlotOut])
def list_slots(
    venture_id: int,
    user: CurrentUser,
    db: DbSession,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    status: SlotStatus | None = None,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 300,
):
    get_accessible_venture(db, venture_id, user)
    query = select(PlanSlot).where(PlanSlot.venture_id == venture_id)
    if start:
        query = query.where(PlanSlot.scheduled_at >= start)
    if end:
        query = query.where(PlanSlot.scheduled_at < end)
    if status:
        query = query.where(PlanSlot.status == status)
    elif not include_archived:
        query = query.where(PlanSlot.status != SlotStatus.archived)
    return db.scalars(query.order_by(PlanSlot.scheduled_at, PlanSlot.id).limit(limit)).all()


@router.post("/slots", response_model=SlotOut, status_code=201)
def create_slot(venture_id: int, body: SlotCreate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    _check_fit(body.platform.value, body.post_type)
    slot = PlanSlot(
        venture_id=venture_id,
        scheduled_at=body.scheduled_at,
        platform=body.platform.value,
        post_type=body.post_type,
        stage=STAGE_OF[body.post_type],
        topic=body.topic,
        pillar=body.pillar,
        cta=body.cta,
        reactive=body.post_type.value == "newsjacking",
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


@router.patch("/slots/{slot_id}", response_model=SlotOut)
def update_slot(venture_id: int, slot_id: int, body: SlotUpdate, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    slot = _get_slot(db, venture_id, slot_id)
    changes = body.model_dump(exclude_unset=True)

    if slot.status in READ_ONLY and CONTENT_FIELDS & changes.keys():
        raise HTTPException(400, f"A {slot.status.value} post can't be edited. Only its status can change.")

    new_platform = changes["platform"].value if "platform" in changes else slot.platform
    new_type = changes.get("post_type", slot.post_type)
    if "platform" in changes or "post_type" in changes:
        _check_fit(new_platform, new_type)

    new_status = changes.get("status", slot.status)
    if new_status != slot.status and new_status not in TRANSITIONS[slot.status]:
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[slot.status])) or "none"
        raise HTTPException(400, f"Can't move from {slot.status.value} to {new_status.value}. Allowed: {allowed}.")
    new_draft = changes["draft"] if "draft" in changes else slot.draft
    if new_status in DRAFT_REQUIRED and not (new_draft or "").strip():
        raise HTTPException(400, f"Write the draft before moving to {new_status.value}.")

    # Hand-edited work must survive "regenerate": a manual change to an unedited idea locks it (unless the user said otherwise).
    if slot.status == SlotStatus.idea and CONTENT_FIELDS & changes.keys() and "locked" not in changes:
        slot.locked = True
    if new_status in APPROVAL_STATUSES and new_status != slot.status and (left := placeholders(new_draft)):
        raise HTTPException(400, f"Fill in or remove the placeholders before approving: {', '.join(left[:4])}")
    for field, value in changes.items():
        if field == "platform":
            value = value.value
        setattr(slot, field, value)
    if "post_type" in changes:
        slot.stage = STAGE_OF[new_type]
        slot.reactive = new_type.value == "newsjacking"
    db.commit()
    db.refresh(slot)
    return slot


@router.delete("/slots/{slot_id}", status_code=204)
def delete_slot(venture_id: int, slot_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    slot = _get_slot(db, venture_id, slot_id)
    if slot.status in {SlotStatus.published, SlotStatus.analysed}:
        raise HTTPException(400, "Published posts can't be deleted. Archive it instead.")
    db.delete(slot)
    db.commit()


@router.post("/slots/{slot_id}/draft", response_model=DraftOut)
def draft_slot(venture_id: int, slot_id: int, body: DraftRequest, request: Request, user: CurrentUser, db: DbSession, settings: SettingsDep):
    """On-demand AI draft in the venture's voice. Returned, not saved: the author reviews, edits and saves it."""
    venture = get_accessible_venture(db, venture_id, user)
    slot = _get_slot(db, venture_id, slot_id)
    if slot.status in READ_ONLY:
        raise HTTPException(400, f"A {slot.status.value} post can't be redrafted.")
    ai: AIProvider | None = request.app.state.ai
    if ai is None:
        raise HTTPException(503, "AI drafting is not configured on this server")
    ensure_budget(db, user, settings)

    brief_row = db.scalar(select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1))
    item = db.get(FeedItem, slot.source_item_id) if slot.source_item_id else None
    context = build_context(
        {"name": venture.name, "niche": venture.niche, "description": venture.description},
        brief_row.data if brief_row else None,
        {"platform": slot.platform, "post_type": slot.post_type.value, "stage": slot.stage.value, "pillar": slot.pillar, "topic": slot.topic, "cta": slot.cta, "draft": slot.draft},
        {"title": item.title, "summary": item.summary, "url": item.url} if item else None,
        body.instructions,
    )
    try:
        result = ai.draft_post(context)
    except AIError as exc:
        raise HTTPException(exc.status_code, exc.message)
    record_usage(db, user, venture.id, "slot_draft", result)
    db.commit()
    return DraftOut(draft=result.post, hooks=result.hooks, notes=result.notes, warnings=check_draft(slot.platform, result.post))
