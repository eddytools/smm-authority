import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.access import get_accessible_venture
from app.deps import CurrentUser, DbSession
from app.framework import DEFAULT_MIX, SlotStatus
from app.insights import PUBLISHED, build_report
from app.metrics_schemas import ImportError_, ImportOut, ImportRequest, MetricsIn, MetricsOut
from app.models import PlanSlot, PostMetric

router = APIRouter(prefix="/ventures/{venture_id}", tags=["performance"])
FIELDS = ("impressions", "reactions", "comments", "shares", "saves", "clicks", "follows", "leads")
MAX_IMPORT_ROWS = 500


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
    for key, value in values.items():
        setattr(metric, key, value)
    metric.source = source
    if slot.status == SlotStatus.published:
        slot.status = SlotStatus.analysed


@router.get("/plan/slots/{slot_id}/metrics", response_model=MetricsOut | None)
def get_metrics(venture_id: int, slot_id: int, user: CurrentUser, db: DbSession):
    get_accessible_venture(db, venture_id, user)
    return _slot(db, venture_id, slot_id).metric


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
