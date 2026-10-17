import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, StringConstraints, model_validator
from typing_extensions import Annotated

from app.models import ItemStatus, SourceType
from app.schemas import ORM, _check_url

_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")
MAX_SOURCES_PER_VENTURE = 20

Label = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class SourceCreate(BaseModel):
    type: SourceType
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    label: Label | None = None

    @model_validator(mode="after")
    def _normalise_target(self):
        t = self.target
        if self.type == SourceType.manual:
            raise ValueError("Manual sources are created by adding an influencer")
        if self.type == SourceType.rss:
            try:
                url = _check_url(t)
            except ValueError:
                url = None
            if not url:
                raise ValueError("RSS target must be an http(s) URL")
            self.target = url
        elif self.type == SourceType.reddit:
            t = re.sub(r"^/?r/", "", t, flags=re.IGNORECASE)
            if not _SUBREDDIT.match(t):
                raise ValueError("Reddit target must be a subreddit name like 'startups' or 'r/startups'")
            self.target = t
        elif len(t) < 2 or len(t) > 200:
            raise ValueError("Google News query must be 2-200 characters")
        return self


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    label: Label | None = None

    @model_validator(mode="after")
    def _enabled_not_null(self):
        if "enabled" in self.model_fields_set and self.enabled is None:
            raise ValueError("enabled cannot be null")
        return self


class SourceOut(ORM):
    id: int
    type: SourceType
    target: str
    label: str | None
    enabled: bool
    last_fetched_at: datetime | None
    last_status: str | None
    last_error: str | None


class FeedItemOut(ORM):
    id: int
    source_id: int
    source_type: str
    source_label: str
    influencer_name: str | None
    url: str
    title: str
    summary: str | None
    author: str | None
    published_at: datetime
    engagement: int
    rule_score: float
    relevance: int | None
    why_it_matters: str | None
    status: ItemStatus


class FeedItemUpdate(BaseModel):
    status: Literal["new", "saved", "dismissed"]


class SourceRefreshResult(BaseModel):
    source_id: int
    status: str
    new_items: int
    error: str | None = None


class RefreshOut(BaseModel):
    new_items: int
    sources: list[SourceRefreshResult]


class ScoreOut(BaseModel):
    scored: int
