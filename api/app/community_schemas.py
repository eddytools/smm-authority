from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator

from app.influencer_schemas import _required_url, _url
from app.schemas import ORM

MAX_COMMUNITIES_PER_VENTURE = 15
CommunityPlatform = Literal["linkedin", "facebook", "slack", "discord", "reddit", "other"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Count = Annotated[int, Field(ge=0, le=1_000_000_000)]


class CommunityCreate(BaseModel):
    name: Name
    platform: CommunityPlatform
    url: Annotated[str, StringConstraints(max_length=500)] | None = None
    notes: Notes | None = None

    _check = field_validator("url")(_url)


class CommunityUpdate(BaseModel):
    notes: Notes | None = None
    url: Annotated[str, StringConstraints(max_length=500)] | None = None
    enabled: bool | None = None

    _check = field_validator("url")(_url)

    @field_validator("enabled")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("cannot be null")
        return v


class CommunityOut(ORM):
    id: int
    name: str
    platform: str
    url: str | None
    notes: str | None
    enabled: bool
    posts_30d: int
    median_engagement: float | None
    last_post_at: datetime | None


class CommunityPostCreate(BaseModel):
    url: Annotated[str, StringConstraints(max_length=1000)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    likes: Count = 0
    comments: Count = 0
    posted_at: AwareDatetime | None = None

    _check = field_validator("url")(_required_url)

    @field_validator("posted_at")
    @classmethod
    def _not_future(cls, v):
        if v is not None and v > datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError("The post date can't be in the future")
        return v
