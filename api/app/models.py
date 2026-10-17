import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    admin = "admin"
    user = "user"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20), default=Role.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ventures: Mapped[list["Venture"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Venture(Base):
    """A venture project. Every later module (brief, feed, calendar) is scoped to one venture."""

    __tablename__ = "ventures"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_venture_owner_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    niche: Mapped[str | None] = mapped_column(String(200), default=None)
    website_url: Mapped[str | None] = mapped_column(String(500), default=None)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="ventures", lazy="joined")
    briefs: Mapped[list["BriefVersion"]] = relationship(back_populates="venture", cascade="all, delete-orphan", passive_deletes=True)
    sources: Mapped[list["Source"]] = relationship(back_populates="venture", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def owner_email(self) -> str:
        return self.owner.email


class BriefVersion(Base):
    """One saved version of a venture's Authority Brief (ICP, ideation, offer, voice, platforms). Append-only."""

    __tablename__ = "brief_versions"
    __table_args__ = (UniqueConstraint("venture_id", "version", name="uq_brief_venture_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    venture: Mapped[Venture] = relationship(back_populates="briefs")


class AIUsage(Base):
    """One row per successful AI call; used for per-user daily limits and cost reporting."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    venture_id: Mapped[int | None] = mapped_column(ForeignKey("ventures.id", ondelete="SET NULL"), default=None)
    feature: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SourceType(str, enum.Enum):
    rss = "rss"
    reddit = "reddit"
    google_news = "google_news"


class Source(Base):
    """Something the ingest job pulls from for one venture: an RSS URL, a subreddit, or a Google News query."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("venture_id", "type", "target", name="uq_source_venture_type_target"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"), index=True)
    type: Mapped[SourceType] = mapped_column(Enum(SourceType, native_enum=False, length=20))
    target: Mapped[str] = mapped_column(String(500))
    label: Mapped[str | None] = mapped_column(String(120), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_status: Mapped[str | None] = mapped_column(String(20), default=None)  # "ok" | "error"
    last_error: Mapped[str | None] = mapped_column(String(300), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    venture: Mapped[Venture] = relationship(back_populates="sources")
    items: Mapped[list["FeedItem"]] = relationship(back_populates="source", cascade="all, delete-orphan", passive_deletes=True)


class ItemStatus(str, enum.Enum):
    new = "new"
    saved = "saved"
    dismissed = "dismissed"


class FeedItem(Base):
    __tablename__ = "feed_items"
    __table_args__ = (
        UniqueConstraint("venture_id", "url_hash", name="uq_feed_venture_urlhash"),
        Index("ix_feed_venture_status", "venture_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    url_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    author: Mapped[str | None] = mapped_column(String(200), default=None)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    engagement: Mapped[int] = mapped_column(Integer, default=0)  # upvotes + comments where the source exposes them
    rule_score: Mapped[float] = mapped_column(Float, default=0.0)  # deterministic 0-100, set by the ingest script
    relevance: Mapped[int | None] = mapped_column(Integer, default=None)  # AI 0-100, only when the user asked for scoring
    why_it_matters: Mapped[str | None] = mapped_column(String(400), default=None)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus, native_enum=False, length=20), default=ItemStatus.new)

    source: Mapped[Source] = relationship(back_populates="items", lazy="joined")

    @property
    def source_type(self) -> str:
        return self.source.type.value

    @property
    def source_label(self) -> str:
        return self.source.label or self.source.target
