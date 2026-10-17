"""Deterministic funnel planner. Pure functions: no DB, no network, no AI (PRD R4: formulas live in code).

Given a venture's brief (platforms + cadence, pillars, offer links) it lays out a week or month of slots:
cadence per platform, best-time windows, a growth -> trust -> sell rhythm, platform-appropriate post types,
pillar coverage, and (optionally) real topics from the trend feed.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.framework import (
    GUIDANCE,
    LABEL,
    PLATFORM_ALLOWED,
    PLATFORM_SCHEDULE,
    ROTATION,
    STAGE_OF,
    WEEK_EMPHASIS,
    PostType,
    Stage,
)

STAGES = [Stage.tofu, Stage.mofu, Stage.bofu]
FEED_TYPES = [PostType.newsjacking, PostType.awareness, PostType.educational]


class PlanningError(Exception):
    pass


@dataclass
class Candidate:
    item_id: int
    title: str
    score: float
    saved: bool


@dataclass
class PlannedSlot:
    scheduled_at: datetime  # aware, UTC
    local_date: date
    platform: str
    week: int
    stage: Stage = Stage.tofu
    post_type: PostType = PostType.educational
    pillar: str | None = None
    topic: str = ""
    cta: str | None = None
    reactive: bool = False
    source_item_id: int | None = None


def allocate(total: int, weights: dict[Stage, float]) -> dict[Stage, int]:
    """Largest-remainder split of `total` by weight. Ties go to earlier stages, so results are deterministic."""
    weight_sum = sum(weights.values())
    quotas = {s: total * weights[s] / weight_sum for s in STAGES}
    counts = {s: int(quotas[s]) for s in STAGES}
    leftover = total - sum(counts.values())
    for s in sorted(STAGES, key=lambda s: (-(quotas[s] - counts[s]), STAGES.index(s)))[:leftover]:
        counts[s] += 1
    return counts


def _week_weights(mix: dict[str, int], week: int, weeks: int) -> dict[Stage, float]:
    base = {s: float(mix[s.value]) for s in STAGES}
    if weeks == 1:  # a single week is balanced, the rhythm only makes sense across a month
        return base
    emphasis = WEEK_EMPHASIS[week % len(WEEK_EMPHASIS)]
    return {s: base[s] * emphasis[s] for s in STAGES}


def _skeleton(brief: dict, start: date, weeks: int, tz: ZoneInfo, skip: set[tuple[str, date]]) -> list[PlannedSlot]:
    slots: list[PlannedSlot] = []
    for plan in brief.get("platforms", []):
        platform = plan["platform"]
        days, at = PLATFORM_SCHEDULE[platform]
        for week in range(weeks):
            window_start = start + timedelta(days=7 * week)
            for k in range(plan["cadence_per_week"]):
                weekday = days[k % 7]
                day = window_start + timedelta(days=(weekday - window_start.weekday()) % 7)
                if (platform, day) in skip:
                    continue
                local = datetime.combine(day, at, tzinfo=tz) + timedelta(hours=4 * (k // 7))
                slots.append(PlannedSlot(local.astimezone(timezone.utc), local.date(), platform, week))
    slots.sort(key=lambda s: (s.scheduled_at, s.platform))
    return slots


def _assign_stages(slots: list[PlannedSlot], mix: dict[str, int], weeks: int) -> None:
    by_week: dict[int, list[PlannedSlot]] = defaultdict(list)
    for s in slots:
        by_week[s.week].append(s)
    for week, week_slots in by_week.items():
        counts = allocate(len(week_slots), _week_weights(mix, week, weeks))
        order = [st for st in STAGES for _ in range(counts[st])]  # growth early in the week, selling late
        for slot, stage in zip(week_slots, order):
            slot.stage = stage

    wanted = [s for s in STAGES if mix[s.value] > 0]
    if len(slots) < len(wanted):
        return
    for missing in wanted:
        if any(s.stage == missing for s in slots):
            continue
        totals = {st: [s for s in slots if s.stage == st] for st in STAGES}
        donor = max(totals, key=lambda st: len(totals[st]))
        if len(totals[donor]) < 2:
            continue
        pool = totals[donor]
        pick = pool[0] if missing == Stage.tofu else pool[-1] if missing == Stage.bofu else pool[len(pool) // 2]
        pick.stage = missing


def _assign_types(slots: list[PlannedSlot]) -> None:
    counters = {s: 0 for s in STAGES}

    def choose(stage: Stage, platform: str) -> tuple[Stage, PostType]:
        chain = {Stage.bofu: [Stage.bofu, Stage.mofu, Stage.tofu], Stage.mofu: [Stage.mofu, Stage.tofu], Stage.tofu: [Stage.tofu]}
        for st in chain[stage]:
            rotation = ROTATION[st]
            for i in range(len(rotation)):
                candidate = rotation[(counters[st] + i) % len(rotation)]
                if candidate in PLATFORM_ALLOWED[platform]:
                    counters[st] += i + 1
                    return st, candidate
        raise PlanningError(f"no post type fits {platform}")  # unreachable: tofu always has an allowed type

    for slot in slots:
        slot.stage, slot.post_type = choose(slot.stage, slot.platform)

    # Guarantee at least one lead magnet in the period when a trust-stage slot on a suitable platform exists.
    if not any(s.post_type == PostType.lead_magnet for s in slots):
        for slot in reversed(slots):
            if slot.stage == Stage.mofu and PostType.lead_magnet in PLATFORM_ALLOWED[slot.platform]:
                slot.post_type = PostType.lead_magnet
                break


def _links(brief: dict) -> tuple[str | None, str | None]:
    offer = brief.get("offer", {})
    return (offer.get("lead_magnets") or [None])[0], offer.get("booking_url") or offer.get("cta_url")


def _fill_content(slots: list[PlannedSlot], brief: dict, candidates: list[Candidate]) -> None:
    pillars = brief.get("ideation", {}).get("pillars") or []
    lead_magnet, link = _links(brief)
    cta_url = brief.get("offer", {}).get("cta_url")

    for i, slot in enumerate(slots):
        slot.pillar = pillars[i % len(pillars)] if pillars else None
        slot.reactive = slot.post_type == PostType.newsjacking
        if slot.post_type == PostType.lead_magnet and lead_magnet:
            slot.cta = f"Offer: {lead_magnet}" + (f" — {cta_url}" if cta_url else "")
        elif slot.post_type in (PostType.conversion, PostType.product_demo, PostType.objection) and link:
            slot.cta = f"Link: {link}"

    # Real topics from the feed: saved first, then best score. Newsjacking gets first pick.
    pool = sorted(candidates, key=lambda c: (not c.saved, -c.score, c.item_id))
    for wanted in FEED_TYPES:
        for slot in slots:
            if slot.post_type == wanted and slot.source_item_id is None and pool:
                item = pool.pop(0)
                slot.topic, slot.source_item_id = item.title[:300], item.item_id

    for slot in slots:
        if not slot.topic:
            prefix = f"[{slot.pillar}] " if slot.pillar else ""
            slot.topic = f"{prefix}{LABEL[slot.post_type]}: {GUIDANCE[slot.post_type]}"[:300]


def generate(
    brief: dict,
    start: date,
    weeks: int,
    tz: ZoneInfo,
    mix: dict[str, int],
    candidates: list[Candidate] | None = None,
    skip: set[tuple[str, date]] | None = None,
) -> list[PlannedSlot]:
    if not brief.get("platforms"):
        raise PlanningError("Choose at least one platform in the Authority setup first.")
    slots = _skeleton(brief, start, weeks, tz, skip or set())
    _assign_stages(slots, mix, weeks)
    _assign_types(slots)
    _fill_content(slots, brief, list(candidates or []))
    for slot in slots:
        assert STAGE_OF[slot.post_type] == slot.stage
    return slots
