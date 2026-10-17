import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.framework import PostType, SlotStatus, Stage


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC in Python. SQLite drops tzinfo on read, which would make the API emit
    times the browser interprets as local; this keeps behaviour identical on SQLite and Postgres."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use timezone-aware values")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="ventures", lazy="joined")
    briefs: Mapped[list["BriefVersion"]] = relationship(back_populates="venture", cascade="all, delete-orphan", passive_deletes=True)
    sources: Mapped[list["Source"]] = relationship(back_populates="venture", cascade="all, delete-orphan", passive_deletes=True)
    plan_slots: Mapped[list["PlanSlot"]] = relationship(back_populates="venture", cascade="all, delete-orphan", passive_deletes=True)
    connections: Mapped[list["Connection"]] = relationship(back_populates="venture", cascade="all, delete-orphan", passive_deletes=True)
    quick_replies: Mapped[list["QuickReply"]] = relationship(back_populates="venture", cascade="all, delete-orphan", passive_deletes=True)

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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class SourceType(str, enum.Enum):
    rss = "rss"
    reddit = "reddit"
    google_news = "google_news"
    manual = "manual"  # posts are pasted in by hand (e.g. an influencer on LinkedIn or X, which can't be read automatically)


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
    last_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    last_status: Mapped[str | None] = mapped_column(String(20), default=None)  # "ok" | "error"
    last_error: Mapped[str | None] = mapped_column(String(300), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    venture: Mapped[Venture] = relationship(back_populates="sources")
    items: Mapped[list["FeedItem"]] = relationship(back_populates="source", cascade="all, delete-orphan", passive_deletes=True)
    influencer: Mapped["Influencer | None"] = relationship(back_populates="source", lazy="joined", cascade="all, delete-orphan", passive_deletes=True, uselist=False)
    community: Mapped["Community | None"] = relationship(back_populates="source", lazy="joined", cascade="all, delete-orphan", passive_deletes=True, uselist=False)

    @property
    def is_managed(self) -> bool:
        """Created and edited through an influencer or community rather than the Sources list."""
        return self.influencer is not None or self.community is not None


class Influencer(Base):
    """A person or publication the venture watches. Their posts arrive through a Source (their RSS/Atom feed when they have
    one, otherwise a manual source) so they land in the same feed and scoring as everything else."""

    __tablename__ = "influencers"
    __table_args__ = (UniqueConstraint("venture_id", "name", name="uq_influencer_venture_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(20))
    profile_url: Mapped[str | None] = mapped_column(String(500), default=None)
    notes: Mapped[str | None] = mapped_column(String(300), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    source: Mapped[Source] = relationship(back_populates="influencer")


class Community(Base):
    """A group the venture's audience hangs out in whose posts are pasted in by hand (LinkedIn/Facebook groups, Slack or
    Discord communities). Subreddits don't need one: they are read automatically through a Reddit source."""

    __tablename__ = "communities"
    __table_args__ = (UniqueConstraint("venture_id", "name", name="uq_community_venture_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(20))
    url: Mapped[str | None] = mapped_column(String(500), default=None)
    notes: Mapped[str | None] = mapped_column(String(300), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    source: Mapped[Source] = relationship(back_populates="community")


class ItemStatus(str, enum.Enum):
    new = "new"
    saved = "saved"
    dismissed = "dismissed"


class FeedItem(Base):
    __tablename__ = "feed_items"
    __table_args__ = (
        UniqueConstraint("venture_id", "url_hash", name="uq_feed_venture_urlhash"),
        Index("ix_feed_venture_status", "venture_id", "status"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    url_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    author: Mapped[str | None] = mapped_column(String(200), default=None)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    engagement: Mapped[int] = mapped_column(Integer, default=0)  # upvotes + comments where the source exposes them
    rule_score: Mapped[float] = mapped_column(Float, default=0.0)  # deterministic 0-100, set by the ingest script
    relevance: Mapped[int | None] = mapped_column(Integer, default=None)  # AI 0-100, only when the user asked for scoring
    why_it_matters: Mapped[str | None] = mapped_column(String(400), default=None)
    scored_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus, native_enum=False, length=20), default=ItemStatus.new)

    source: Mapped[Source] = relationship(back_populates="items", lazy="joined")

    @property
    def source_type(self) -> str:
        return self.source.type.value

    @property
    def influencer_name(self) -> str | None:
        return self.source.influencer.name if self.source.influencer else None

    @property
    def source_label(self) -> str:
        return self.source.label or self.source.target


class PlanSlot(Base):
    """One planned post on the calendar. Content (`topic`, `draft`) is edited by the user; the planner only proposes."""

    __tablename__ = "plan_slots"
    # sqlite_autoincrement: never reuse the id of a deleted slot, so a stale id in a browser can't hit a different slot
    __table_args__ = (Index("ix_plan_venture_time", "venture_id", "scheduled_at"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime())
    platform: Mapped[str] = mapped_column(String(20))
    post_type: Mapped[PostType] = mapped_column(Enum(PostType, native_enum=False, length=20))
    stage: Mapped[Stage] = mapped_column(Enum(Stage, native_enum=False, length=10))
    pillar: Mapped[str | None] = mapped_column(String(300), default=None)
    topic: Mapped[str] = mapped_column(String(300))
    cta: Mapped[str | None] = mapped_column(String(500), default=None)
    draft: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[SlotStatus] = mapped_column(Enum(SlotStatus, native_enum=False, length=20), default=SlotStatus.idea)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # regenerating the plan never removes locked slots
    reactive: Mapped[bool] = mapped_column(Boolean, default=False)  # reserved for a timely/reactive post
    source_item_id: Mapped[int | None] = mapped_column(ForeignKey("feed_items.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    venture: Mapped[Venture] = relationship(back_populates="plan_slots")
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    external_id: Mapped[str | None] = mapped_column(String(200), default=None)  # id of the post on the platform
    external_url: Mapped[str | None] = mapped_column(String(500), default=None)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    publish_error: Mapped[str | None] = mapped_column(String(500), default=None)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)  # set while a worker is posting it

    metric: Mapped["PostMetric | None"] = relationship(back_populates="slot", uselist=False, cascade="all, delete-orphan", passive_deletes=True, lazy="joined")

    @property
    def will_auto_publish(self) -> bool:
        """Scheduled, and the venture has a live connection for this platform with auto-posting on."""
        return self.status == SlotStatus.scheduled and any(
            c.platform == self.platform and c.status == "active" and c.auto_publish for c in self.venture.connections
        )

    @property
    def has_metrics(self) -> bool:
        return self.metric is not None

    @property
    def warnings(self) -> list[str]:
        from app.drafting import check_draft  # local import: drafting imports framework only, keep models import-light

        return check_draft(self.platform, self.draft)


class PostMetric(Base):
    """Results for one published post (one row per post, updated in place). Entered by hand or imported from CSV
    until platform analytics APIs are connected."""

    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("plan_slots.id", ondelete="CASCADE"), unique=True)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    reactions: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    follows: Mapped[int] = mapped_column(Integer, default=0)
    leads: Mapped[int] = mapped_column(Integer, default=0)  # leads the author attributes to this post
    source: Mapped[str] = mapped_column(String(10), default="manual")  # "manual" | "csv"
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    slot: Mapped[PlanSlot] = relationship(back_populates="metric", lazy="joined")


class Connection(Base):
    """A venture's authorised account on a publishing platform. Tokens are stored encrypted and never returned by the API."""

    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("venture_id", "platform", name="uq_connection_venture_platform"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[str] = mapped_column(String(200))
    account_name: Mapped[str] = mapped_column(String(200))
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")  # "active" | "needs_reconnect"
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=True)  # per-venture kill switch for automatic posting
    connected_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    venture: Mapped[Venture] = relationship(back_populates="connections")


class OAuthAttempt(Base):
    """One in-flight 'Connect' click. The PKCE verifier lives here, server-side, never in a URL the browser sees."""

    __tablename__ = "oauth_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(100), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    code_verifier: Mapped[str | None] = mapped_column(String(200), default=None)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class QuickReply(Base):
    """A drafted reply to someone else's thread or post. Never posted by the app: the author copies it and posts it themselves."""

    __tablename__ = "quick_replies"
    __table_args__ = (UniqueConstraint("venture_id", "source_key", name="uq_reply_venture_source"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(primary_key=True)
    venture_id: Mapped[int] = mapped_column(ForeignKey("ventures.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    community: Mapped[str | None] = mapped_column(String(100), default=None)
    source_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    source_key: Mapped[str | None] = mapped_column(String(64), default=None)  # hash of the normalised URL: one draft per thread
    feed_item_id: Mapped[int | None] = mapped_column(ForeignKey("feed_items.id", ondelete="SET NULL"), default=None)
    question_text: Mapped[str] = mapped_column(Text)
    community_rules: Mapped[str | None] = mapped_column(Text, default=None)
    reply_draft: Mapped[str] = mapped_column(Text)
    post_idea_title: Mapped[str | None] = mapped_column(String(200), default=None)
    post_idea: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(String(500), default=None)
    promo_terms: Mapped[list] = mapped_column(JSON, default=list)  # identifies the author's own business when checking the draft
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | posted | dismissed
    plan_slot_id: Mapped[int | None] = mapped_column(ForeignKey("plan_slots.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    venture: Mapped[Venture] = relationship(back_populates="quick_replies")

    @property
    def warnings(self) -> list[str]:
        from app.replies import check_reply, parse_rules

        return check_reply(self.platform, self.reply_draft, parse_rules(self.community_rules), self.promo_terms or [])
