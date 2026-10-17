import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.access import get_accessible_venture
from app.deps import CurrentUser, DbSession
from app.framework import DEFAULT_MIX, SlotStatus
from app.analytics import AUTO_FIELDS, PULL_AFTER, refresh_slot, supports_metrics
from app.insights import PUBLISHED, build_report
from app.metrics_schemas import ImportError_, ImportOut, ImportRequest, MetricsIn, MetricsOut
from app.models import PlanSlot, PostMetric
from app.publishing import _as_utc as as_utc, active_connection

router = APIRouter(prefix="/ventures/{venture_id}", tags=["performance"])
FIELDS = ("impressions", "reactions", "comments", "shares", "saves", "clicks", "follows", "leads")
MAX_IMPORT_ROWS = 500
REFRESH_MIN_SECONDS = 120


def _slot(db, venture_id: int, slot_id: int) -> PlanSlot:
    slot = db.get(PlanSlot, slot_id)
    if slot is None or slot.venture_id != venture_id:
        raise HTTPException(404, "Slot not found")
    return slot


def _save(db, slot: PlanSlot, values: dict, source: str) -> None:
    """Upsert, and a first result moves a Published post to Analysed (the pipeline's last step)."""
    if slot.status.value not in PUBLISHED:
        raise HTTPException(400, "Results can only be recorded for published posts.")
    metric = slot.metric
    if metric is None:
        metric = PostMetric(slot_id=slot.id)
        slot.metric = metric
    # Numbers pulled from the platform stay "auto" while you only add what it can't see (clicks, follows, leads); changing a
    # platform number yourself makes it yours, and the scheduled pull stops overwriting it.
    keeps_auto = metric.source == "auto" and all(getattr(metric, f) == values.get(f, getattr(metric, f)) for f in AUTO_FIELDS)
    for key, value in values.items():
        setattr(metric, key, value)
    if not keeps_auto:
        metric.source = source
    if slot.status == SlotStatus.published:
        slot.status = SlotStatus.analysed


@router.get("/plan/slots/{slot_id}/metrics", response_model=MetricsOut | None)
def get_metrics(venture_id: int, slot_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    return _slot(db, venture_id, slot_id).metric


@router.get("/plan/slots/{slot_id}/metrics/auto")
def auto_status(venture_id: int, slot_id: int, request: Request, user: CurrentUser, db: DbSession):
    """Whether this post's numbers come from the platform, and when the next scheduled pull is."""
    get_accessible_venture(db, venture_id, user)
    slot = _slot(db, venture_id, slot_id)
    publishing = request.app.state.publishing
    supported = supports_metrics(publishing, slot.platform)
    connected = supported and active_connection(db, venture_id, slot.platform) is not None
    next_at = None
    if supported and slot.external_id and slot.published_at and slot.metrics_pull_count < len(PULL_AFTER) and (slot.metric is None or slot.metric.source == "auto"):
        next_at = as_utc(slot.published_at) + PULL_AFTER[slot.metrics_pull_count]
    return {
        "supported": supported, "connected": connected, "published_here": bool(slot.external_id),
        "source": slot.metric.source if slot.metric else None, "last_pulled_at": slot.metrics_pulled_at, "error": slot.metrics_error,
        "pulls_done": min(slot.metrics_pull_count, len(PULL_AFTER)), "pulls_total": len(PULL_AFTER), "next_pull_at": next_at,
    }


@router.post("/plan/slots/{slot_id}/metrics/refresh", response_model=MetricsOut)
def refresh_metrics(venture_id: int, slot_id: int, request: Request, user: CurrentUser, db: DbSession):
    """Read this post's numbers from the platform now (and hand it back to automatic updates)."""
    get_accessible_venture(db, venture_id, user)
    slot = _slot(db, venture_id, slot_id)
    pulled = slot.metrics_pulled_at
    if pulled is not None and (datetime.now(timezone.utc) - as_utc(pulled)).total_seconds() < REFRESH_MIN_SECONDS:
        raise HTTPException(429, "Refreshed a moment ago. Try again in a few minutes.")
    out = refresh_slot(db, slot, request.app.state.publishing)
    if out.status == "skipped":
        raise HTTPException(400, out.message)
    if out.status == "reconnect":
        raise HTTPException(409, out.message or "Reconnect the account.")
    if out.status != "updated":
        raise HTTPException(502, out.message or "The platform didn't return numbers for this post.")
    db.refresh(slot)
    return slot.metric


@router.put("/plan/slots/{slot_id}/metrics", response_model=MetricsOut)
def put_metrics(venture_id: int, slot_id: int, body: MetricsIn, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    slot = _slot(db, venture_id, slot_id)
    _save(db, slot, body.model_dump(), "manual")
    db.commit()
    db.refresh(slot)
    return slot.metric


@router.post("/metrics/import", response_model=ImportOut)
def import_metrics(venture_id: int, body: ImportRequest, user: CurrentUser, db: DbSession):
    """CSV with a `slot_id` column and any of: impressions, reactions, comments, shares, saves, clicks, follows, leads.
    Valid rows are imported even if others fail; every failure is reported with its row number."""
    get_accessible_venture(db, venture_id, user)
    reader = csv.DictReader(io.StringIO(body.csv.lstrip("﻿")))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    if "slot_id" not in header or not set(header) & set(FIELDS):
        raise HTTPException(400, "The CSV needs a slot_id column and at least one of: " + ", ".join(FIELDS))
    imported, errors = 0, []
    for number, raw in enumerate(reader, start=2):  # row 1 is the header
        if number - 1 > MAX_IMPORT_ROWS:
            errors.append(ImportError_(row=number, message=f"Stopped: more than {MAX_IMPORT_ROWS} rows."))
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            slot_id = int(row["slot_id"])
            values = {f: MetricsIn(**{f: int(row[f])}).model_dump()[f] for f in FIELDS if row.get(f, "") != ""}
        except (ValueError, KeyError, TypeError):
            errors.append(ImportError_(row=number, message="Every number must be a whole number of 0 or more."))
            continue
        except Exception:
            errors.append(ImportError_(row=number, message="A value is out of range."))
            continue
        slot = db.get(PlanSlot, slot_id)
        if slot is None or slot.venture_id != venture_id:
            errors.append(ImportError_(row=number, message=f"No planned post with id {slot_id} in this venture."))
            continue
        if slot.status.value not in PUBLISHED:
            errors.append(ImportError_(row=number, message=f"Post {slot_id} isn't published yet."))
            continue
        _save(db, slot, values, "csv")
        imported += 1
    db.commit()
    return ImportOut(imported=imported, errors=errors)


@router.get("/insights")
def insights(venture_id: int, user: CurrentUser, db: DbSession, days: Annotated[int, Query(ge=7, le=365)] = 90,
    tofu: Annotated[int, Query(ge=0, le=100)] = DEFAULT_MIX["tofu"],
    mofu: Annotated[int, Query(ge=0, le=100)] = DEFAULT_MIX["mofu"],
    bofu: Annotated[int, Query(ge=0, le=100)] = DEFAULT_MIX["bofu"],
):
    """What worked / what didn't. Deterministic: no AI is involved."""
    get_accessible_venture(db, venture_id, user)
    if tofu + mofu + bofu != 100:
        raise HTTPException(422, "The funnel mix must add up to 100")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    slots = db.scalars(select(PlanSlot).where(PlanSlot.venture_id == venture_id, PlanSlot.scheduled_at >= since, PlanSlot.scheduled_at <= now)).unique().all()
    rows = [
        {
            "slot_id": s.id, "scheduled_at": s.scheduled_at, "platform": s.platform, "pillar": s.pillar, "post_type": s.post_type.value, "stage": s.stage.value,
            "topic": s.topic, "status": s.status.value, "metrics": {f: getattr(s.metric, f) for f in FIELDS} if s.metric else None,
        }
        for s in slots
    ]
    return build_report(rows, now, since, days, {"tofu": tofu, "mofu": mofu, "bofu": bofu})
