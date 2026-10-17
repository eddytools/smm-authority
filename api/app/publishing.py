"""Posting a scheduled slot to LinkedIn / X, safely. Used by the scheduled job and by 'Publish now'.

Guarantees worth knowing:
- A slot is *claimed* with one atomic UPDATE before anything is sent, so two workers (or a job and a button press)
  never post it twice. A claim older than 15 minutes is considered a crashed worker and can be re-taken.
- Only human-approved, Scheduled posts are ever sent, and only on platforms the venture has connected with auto-post on
  (or when the user presses Publish now).
- Failures are classified: transient -> retry with backoff (5m, 15m, 1h, then give up); reconnect needed -> stop and
  tell the user; anything else -> stop with the platform's message. Nothing retries a thread that went out partly.
- Posts more than N hours (default 24) past their time are not posted automatically after downtime.
- Tokens are decrypted only here, refreshed when close to expiry (and the new refresh token is saved before use)."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.crypto import TokenCipher, TokenCipherError
from app.framework import SlotStatus
from app.models import Connection, PlanSlot
from app.publishers import PartialPublishError, ProviderError

log = logging.getLogger("smm.publish")
BACKOFF_MINUTES = [5, 15, 60]
MAX_ATTEMPTS = 4
CLAIM_STALE = timedelta(minutes=15)
REFRESH_MARGIN = timedelta(minutes=5)


class Publishing:
    """The providers and cipher the API and the job share."""

    def __init__(self, providers: dict, cipher: TokenCipher | None, settings: Settings):
        self.providers, self.cipher, self.settings = providers, cipher, settings

    def configured(self, platform: str) -> bool:
        p = self.providers.get(platform)
        return bool(p and p.configured and self.cipher)


@dataclass
class Outcome:
    slot_id: int
    status: str  # published | retry | failed | reconnect | skipped
    message: str | None = None


def active_connection(db: Session, venture_id: int, platform: str) -> Connection | None:
    return db.scalar(select(Connection).where(Connection.venture_id == venture_id, Connection.platform == platform, Connection.status == "active"))


def _as_utc(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fresh_token(db: Session, conn: Connection, publishing: Publishing, now: datetime) -> str:
    cipher, provider = publishing.cipher, publishing.providers[conn.platform]
    try:
        access = cipher.decrypt(conn.access_token_enc)
        expires = _as_utc(conn.expires_at)
        if expires is None or expires - now > REFRESH_MARGIN:
            return access
        if not conn.refresh_token_enc:
            raise ProviderError(f"The {provider.label} connection expired. Reconnect the account.", reauth=True)
        tokens = provider.refresh(cipher.decrypt(conn.refresh_token_enc))
    except TokenCipherError as exc:
        raise ProviderError(str(exc), reauth=True)
    except ProviderError as exc:
        if exc.transient or exc.reauth:
            raise
        raise ProviderError(f"The {provider.label} connection could not be renewed. Reconnect the account.", reauth=True)
    conn.access_token_enc = cipher.encrypt(tokens.access_token)
    if tokens.refresh_token:  # providers may rotate it: persist BEFORE using the new access token
        conn.refresh_token_enc = cipher.encrypt(tokens.refresh_token)
    conn.expires_at = now + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    db.commit()
    return tokens.access_token


def _release(db: Session, slot: PlanSlot) -> None:
    slot.claimed_at = None
    db.commit()


def reset_publish_state(slot: PlanSlot) -> None:
    slot.publish_error, slot.publish_attempts, slot.next_attempt_at = None, 0, None


def publish_slot(db: Session, slot: PlanSlot, publishing: Publishing, now: datetime | None = None) -> Outcome:
    now = now or datetime.now(timezone.utc)
    provider = publishing.providers.get(slot.platform)
    conn = active_connection(db, slot.venture_id, slot.platform)
    if provider is None or conn is None or publishing.cipher is None:
        return Outcome(slot.id, "skipped", "No active connection for this platform.")

    claimed = db.execute(
        update(PlanSlot)
        .where(PlanSlot.id == slot.id, PlanSlot.status == SlotStatus.scheduled, or_(PlanSlot.claimed_at.is_(None), PlanSlot.claimed_at < now - CLAIM_STALE))
        .values(claimed_at=now)
    )
    db.commit()
    if claimed.rowcount != 1:
        return Outcome(slot.id, "skipped", "Already being posted, or no longer scheduled.")
    db.refresh(slot)

    try:
        token = _fresh_token(db, conn, publishing, now)
        result = provider.publish(token, conn.account_id, conn.account_name, slot.draft or "")
    except PartialPublishError as exc:  # some parts are live: mark published (never retry), keep the explanation
        slot.status, slot.published_at, slot.external_id, slot.external_url = SlotStatus.published, now, exc.first_id, exc.first_url
        slot.publish_error, slot.next_attempt_at, slot.publish_attempts = exc.message[:500], None, slot.publish_attempts + 1
        _release(db, slot)
        return Outcome(slot.id, "published", exc.message)
    except ProviderError as exc:
        slot.publish_attempts += 1
        slot.publish_error = exc.message[:500]
        if exc.reauth:
            conn.status = "needs_reconnect"
            slot.next_attempt_at = None
            kind = "reconnect"
        elif exc.transient and slot.publish_attempts < MAX_ATTEMPTS:
            slot.next_attempt_at = now + timedelta(minutes=BACKOFF_MINUTES[min(slot.publish_attempts - 1, len(BACKOFF_MINUTES) - 1)])
            kind = "retry"
        else:
            slot.next_attempt_at = None
            if exc.transient:
                slot.publish_error = f"Gave up after {MAX_ATTEMPTS} attempts. {exc.message}"[:500]
            kind = "failed"
        log.warning("slot %s on %s: %s -> %s", slot.id, slot.platform, exc.message, kind)
        _release(db, slot)
        return Outcome(slot.id, kind, slot.publish_error)

    slot.status, slot.published_at = SlotStatus.published, now
    slot.external_id, slot.external_url = result.external_id, result.url
    slot.publish_error, slot.next_attempt_at, slot.publish_attempts = None, None, slot.publish_attempts + 1
    _release(db, slot)
    return Outcome(slot.id, "published")


def run_due(session_factory: sessionmaker, publishing: Publishing, now: datetime | None = None) -> list[Outcome]:
    """One pass: post every Scheduled slot whose time has come on a connected platform. Safe to run every minute."""
    now = now or datetime.now(timezone.utc)
    outcomes: list[Outcome] = []
    if not publishing.cipher:
        return outcomes
    lateness = timedelta(hours=publishing.settings.publish_max_lateness_hours)
    with session_factory() as db:
        due = db.scalars(
            select(PlanSlot)
            .where(
                PlanSlot.status == SlotStatus.scheduled,
                PlanSlot.scheduled_at <= now,
                PlanSlot.platform.in_(list(publishing.providers)),
                or_(PlanSlot.publish_error.is_(None), and_(PlanSlot.next_attempt_at.is_not(None), PlanSlot.next_attempt_at <= now)),
            )
            .order_by(PlanSlot.scheduled_at, PlanSlot.id)
        ).unique().all()
        for slot in due:
            try:
                conn = active_connection(db, slot.venture_id, slot.platform)
                if conn is None or not conn.auto_publish:
                    continue  # manual platform, paused, or waiting for a reconnect: leave it for the human
                if now - _as_utc(slot.scheduled_at) > lateness:
                    slot.publish_error = f"Missed its time by more than {publishing.settings.publish_max_lateness_hours} hours, so it was not posted automatically. Reschedule it or use Publish now."
                    slot.next_attempt_at = None
                    db.commit()
                    outcomes.append(Outcome(slot.id, "failed", slot.publish_error))
                    continue
                outcomes.append(publish_slot(db, slot, publishing, now))
            except Exception:  # one bad slot must never stop the rest
                db.rollback()
                log.exception("unexpected error publishing slot %s", slot.id)
                outcomes.append(Outcome(slot.id, "failed", "Unexpected error. See the server log."))
    return outcomes
