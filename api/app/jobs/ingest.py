"""Scheduled ingest script: pull every enabled source, normalise, dedupe, rule-score, prune.

Run from cron (see README):   python -m app.jobs.ingest [--venture ID]
No AI is used here. Safe to run repeatedly (idempotent: items are keyed by normalised URL per venture).
"""

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import init_schema, make_engine
from app.feed_parsers import ParseError, build_url, parse_for, url_hash
from app.fetch import FetchError, FetchResult, safe_fetch
from app.jobs.scoring import brief_keywords, rule_score
from app.models import BriefVersion, FeedItem, ItemStatus, Source, Venture

log = logging.getLogger("smm.ingest")
Fetcher = Callable[[str, str], FetchResult]  # (url, accept) -> result


def build_fetcher(settings: Settings) -> Fetcher:
    def fetch(url: str, accept: str) -> FetchResult:
        return safe_fetch(url, user_agent=settings.fetch_user_agent, allow_private=settings.allow_private_fetch, accept=accept)

    return fetch


@dataclass
class SourceReport:
    source_id: int
    status: str
    new_items: int = 0
    error: str | None = None


@dataclass
class IngestReport:
    sources: list[SourceReport] = field(default_factory=list)

    @property
    def new_items(self) -> int:
        return sum(s.new_items for s in self.sources)


def _latest_brief(db: Session, venture_id: int) -> dict | None:
    row = db.scalar(select(BriefVersion).where(BriefVersion.venture_id == venture_id).order_by(BriefVersion.version.desc()).limit(1))
    return row.data if row else None


def ingest_venture(db: Session, venture: Venture, fetch: Fetcher, settings: Settings, now: datetime | None = None) -> IngestReport:
    now = now or datetime.now(timezone.utc)
    report = IngestReport()
    kws = brief_keywords(venture.name, venture.niche, _latest_brief(db, venture.id))
    sources = db.scalars(select(Source).where(Source.venture_id == venture.id, Source.enabled.is_(True)).order_by(Source.id)).all()

    for source in sources:
        sr = SourceReport(source_id=source.id, status="ok")
        try:
            accept = "application/json" if source.type.value == "reddit" else "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5"
            result = fetch(build_url(source.type.value, source.target), accept)
            raw_items = parse_for(source.type.value, result.body, now)
            known = set(db.scalars(select(FeedItem.url_hash).where(FeedItem.venture_id == venture.id)))
            for raw in raw_items:
                h = url_hash(raw.url)
                if h in known:
                    continue
                known.add(h)
                db.add(
                    FeedItem(
                        venture_id=venture.id,
                        source_id=source.id,
                        url=raw.url,
                        url_hash=h,
                        title=raw.title,
                        summary=raw.summary,
                        author=raw.author,
                        published_at=raw.published_at,
                        fetched_at=now,
                        engagement=raw.engagement,
                        rule_score=rule_score(raw.title, raw.summary, raw.published_at, raw.engagement, kws, now),
                    )
                )
                sr.new_items += 1
            db.flush()
            source.last_status, source.last_error = "ok", None
        except (FetchError, ParseError) as exc:
            sr.status, sr.error = "error", str(exc)[:300]
            source.last_status, source.last_error = "error", sr.error
            log.warning("source %s failed: %s", source.id, sr.error)
        except IntegrityError:  # a parallel run inserted the same URL; the other run wins
            db.rollback()
            source = db.get(Source, source.id)
            sr.status, sr.error = "error", "concurrent ingest, retry"
        source.last_fetched_at = now
        db.commit()
        report.sources.append(sr)

    prune(db, venture.id, settings, now)
    return report


def prune(db: Session, venture_id: int, settings: Settings, now: datetime) -> None:
    """Drop old items nobody saved. Dismissed ones are kept for the retention window so they don't reappear."""
    cutoff = now - timedelta(days=settings.feed_retention_days)
    db.execute(delete(FeedItem).where(FeedItem.venture_id == venture_id, FeedItem.status != ItemStatus.saved, FeedItem.fetched_at < cutoff))
    db.commit()


def run_all(session_factory: sessionmaker, settings: Settings, fetch: Fetcher | None = None, venture_id: int | None = None) -> IngestReport:
    fetch = fetch or build_fetcher(settings)
    total = IngestReport()
    with session_factory() as db:
        query = select(Venture).where(Venture.is_archived.is_(False)).order_by(Venture.id)
        if venture_id is not None:
            query = query.where(Venture.id == venture_id)
        for venture in db.scalars(query).unique().all():
            total.sources += ingest_venture(db, venture, fetch, settings).sources
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--venture", type=int, help="only this venture id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    init_schema(engine)
    report = run_all(sessionmaker(bind=engine, expire_on_commit=False), settings, venture_id=args.venture)
    failed = sum(s.status == "error" for s in report.sources)
    log.info("ingest done: %d sources, %d new items, %d failed", len(report.sources), report.new_items, failed)


if __name__ == "__main__":
    main()
