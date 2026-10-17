from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator

from app.schemas import ORM

MAX_INFLUENCERS_PER_VENTURE = 25
Platform = Literal["linkedin", "x", "reddit", "youtube", "blog", "newsletter", "other"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


def _url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Must be an http(s) URL")
    return url


def _required_url(value: str) -> str:
    url = _url(value)
    if url is None:
        raise ValueError("A link is required")
    return url


class InfluencerCreate(BaseModel):
    name: Name
    platform: Platform
    profile_url: Annotated[str, StringConstraints(max_length=500)] | None = None
    feed_url: Annotated[str, StringConstraints(max_length=500)] | None = None  # an RSS/Atom URL, when they publish one
    notes: Notes | None = None

    _check = field_validator("profile_url", "feed_url")(_url)


class InfluencerUpdate(BaseModel):
    name: Name | None = None
    profile_url: Annotated[str, StringConstraints(max_length=500)] | None = None
    notes: Notes | None = None
    enabled: bool | None = None

    _check = field_validator("profile_url")(_url)

    @field_validator("name", "enabled")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("cannot be null")
        return v


class InfluencerOut(ORM):
    id: int
    name: str
    platform: str
    profile_url: str | None
    notes: str | None
    source_id: int
    feed_url: str | None
    enabled: bool
    posts_30d: int
    avg_engagement: float | None
    last_post_at: datetime | None
    last_status: str | None
    last_error: str | None


class PostCreate(BaseModel):
    url: Annotated[str, StringConstraints(max_length=1000)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    posted_at: AwareDatetime | None = None
    engagement: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0  # reactions + comments, as shown on the post

    _check = field_validator("url")(_required_url)

    @field_validator("posted_at")
    @classmethod
    def _not_future(cls, v):
        if v is not None and v > datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError("The post date can't be in the future")
        return v


class PostOut(ORM):
    id: int
    title: str
    url: str
    engagement: int
    published_at: datetime
