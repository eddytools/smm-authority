"""Pulling results for published posts from the platform, safely. Used by the scheduled job and the 'Refresh' button.

What it does and doesn't do:
- Only platforms whose provider can read post numbers are pulled (X). LinkedIn only offers analytics to approved partner
  apps, so LinkedIn results stay hand-entered.
- Pulls happen 1, 3, 7 and 14 days after publishing (numbers settle over days; four reads per post keep API use low),
  batched per connection. Nothing is pulled for a post that has no connection, or after a reconnect is needed.
- It only writes the fields the platform returns (impressions, reactions, comments, shares, saves). Link clicks, follows and
  leads stay whatever the author entered.
- Numbers the author typed or imported are never overwritten by the scheduled job. Pressing Refresh is the explicit way to
  hand a post back to automatic updates.
- Errors are classified like publishing: transient -> try again next pass; reconnect needed -> mark the connection and stop;
  not permitted (HTTP 403, e.g. the X API plan does not include reading posts) or post gone -> stop for that post and say why."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.framework import SlotStatus
from app.models import Connection, PlanSlot, PostMetric
from app.publishers import ProviderError
from app.publishing import Publishing, _as_utc as as_utc, _fresh_token, active_connection

log = logging.getLogger("smm.analytics")
PULL_AFTER = [timedelta(days=1), timedelta(days=3), timedelta(days=7), timedelta(days=14)]
BATCH = 100  # X accepts up to 100 ids per request
AUTO_FIELDS = ("impressions", "reactions", "comments", "shares", "saves")
PUBLISHED = (SlotStatus.published, SlotStatus.analysed)
PLATFORM_NAME = {"x": "X", "linkedin": "LinkedIn"}


@dataclass
class PullOutcome:
    slot_id: int
    status: str  # updated | missing | forbidden | retry | reconnect | skipped
    message: str | None = None


def supports_metrics(publishing: Publishing, platform: str) -> bool:
    p = publishing.providers.get(platform)
    return bool(p and getattr(p, "metrics_supported", False) and publishing.cipher)


def is_due(slot: PlanSlot, now: datetime) -> bool:
    if slot.metric is not None and slot.metric.source != "auto":
        return False  # the author's own numbers win
    if slot.metrics_pull_count >= len(PULL_AFTER) or slot.published_at is None or not slot.external_id:
        return False
    return now - as_utc(slot.published_at) >= PULL_AFTER[slot.metrics_pull_count]


def _apply(slot: PlanSlot, values: dict[str, int], now: datetime, *, forced: bool) -> None:
    metric = slot.metric
    if metric is None:
        metric = PostMetric(slot_id=slot.id, source="auto")
        slot.metric = metric
    elif forced:
        metric.source = "auto"
    for key, value in values.items():
        if key in AUTO_FIELDS:
            setattr(metric, key, value)
    if slot.status == SlotStatus.published:
        slot.status = SlotStatus.analysed
    slot.metrics_pulled_at, slot.metrics_error = now, None
    if not forced:
        slot.metrics_pull_count += 1


def _stop(slot: PlanSlot, message: str) -> None:
    slot.metrics_pull_count, slot.metrics_error = len(PULL_AFTER), message[:300]


def _pull(db: Session, conn: Connection, slots: list[PlanSlot], publishing: Publishing, now: datetime, *, forced: bool) -> list[PullOutcome]:
    provider = publishing.providers[conn.platform]
    outcomes: list[PullOutcome] = []
    try:
        token = _fresh_token(db, conn, publishing, now)
    except ProviderError as exc:
        return _provider_failure(db, conn, slots, exc, outcomes, forced)
    for i in range(0, len(slots), BATCH):
        chunk = slots[i : i + BATCH]
        try:
            result = provider.fetch_metrics(token, [s.external_id for s in chunk])
        except ProviderError as exc:
            return outcomes + _provider_failure(db, conn, [s for s in slots[i:]], exc, [], forced)
        for slot in chunk:
            values = result.get(slot.external_id)
            if values is None:
                _stop(slot, f"This post wasn't found on {provider.label}. It may have been deleted. Enter results by hand if you need them.")
                outcomes.append(PullOutcome(slot.id, "missing", slot.metrics_error))
            else:
                _apply(slot, values, now, forced=forced)
                outcomes.append(PullOutcome(slot.id, "updated"))
        db.commit()
    return outcomes


def _provider_failure(db: Session, conn: Connection, slots: list[PlanSlot], exc: ProviderError, outcomes: list[PullOutcome], forced: bool) -> list[PullOutcome]:
    if exc.reauth:
        conn.status = "needs_reconnect"
        kind = "reconnect"
        for s in slots:
            s.metrics_error = exc.message[:300]
    elif exc.status == 403:
        kind = "forbidden"
        for s in slots:
            _stop(s, f"{PLATFORM_NAME.get(conn.platform, conn.platform)} didn't allow reading post numbers (403). Your app's API access level may not include it. Enter results by hand.")
    else:  # transient or unexplained: leave the schedule alone so the next pass tries again
        kind = "retry"
        for s in slots:
            s.metrics_error = exc.message[:300]
    log.warning("metrics pull on %s: %s -> %s", conn.platform, exc.message, kind)
    db.commit()
    return outcomes + [PullOutcome(s.id, kind, s.metrics_error) for s in slots]


def run_pulls(session_factory: sessionmaker, publishing: Publishing, now: datetime | None = None) -> list[PullOutcome]:
    """One pass over every post that is due. Safe to run hourly."""
    now = now or datetime.now(timezone.utc)
    outcomes: list[PullOutcome] = []
    if not publishing.cipher:
        return outcomes
    with session_factory() as db:
        candidates = db.scalars(
            select(PlanSlot).where(PlanSlot.status.in_(PUBLISHED), PlanSlot.external_id.is_not(None), PlanSlot.metrics_pull_count < len(PULL_AFTER), PlanSlot.platform.in_(list(publishing.providers)))
            .order_by(PlanSlot.published_at, PlanSlot.id)
        ).unique().all()
        groups: dict[tuple[int, str], list[PlanSlot]] = {}
        for slot in candidates:
            if supports_metrics(publishing, slot.platform) and is_due(slot, now):
                groups.setdefault((slot.venture_id, slot.platform), []).append(slot)
        for (venture_id, platform), slots in groups.items():
            conn = active_connection(db, venture_id, platform)
            if conn is None:
                continue  # disconnected: nothing to pull with, and nothing to report as a failure
            try:
                outcomes += _pull(db, conn, slots, publishing, now, forced=False)
            except Exception:  # one connection must never stop the rest
                db.rollback()
                log.exception("unexpected error pulling metrics for venture %s on %s", venture_id, platform)
    return outcomes


def refresh_slot(db: Session, slot: PlanSlot, publishing: Publishing, now: datetime | None = None) -> PullOutcome:
    """The 'Refresh' button: read this post's numbers now, and hand it back to automatic updates."""
    now = now or datetime.now(timezone.utc)
    if slot.status not in PUBLISHED or not slot.external_id:
        return PullOutcome(slot.id, "skipped", "Only a post that was published through the app can be refreshed from the platform.")
    if not supports_metrics(publishing, slot.platform):
        return PullOutcome(slot.id, "skipped", "This platform doesn't let the app read post numbers. Enter them by hand.")
    conn = active_connection(db, slot.venture_id, slot.platform)
    if conn is None:
        return PullOutcome(slot.id, "skipped", "Connect the account first (Publishing page).")
    stopped = slot.metrics_pull_count
    out = _pull(db, conn, [slot], publishing, now, forced=True)[0]
    if out.status == "updated":
        slot.metrics_pull_count = stopped  # a manual refresh doesn't use up or restore scheduled pulls
        db.commit()
    return out
