from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, StringConstraints, model_validator

from app.brief_schemas import Platform
from app.framework import PostType
from app.schemas import ORM, WebsiteUrl

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=6000)]
Rules = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]
Instructions = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


def _community(value: str) -> str | None:
    value = value.strip()
    value = value[2:] if value.lower().startswith("r/") else value[3:] if value.lower().startswith("/r/") else value
    return value[:100] or None


Community = Annotated[str, AfterValidator(_community)]


class ReplyRequest(BaseModel):
    """Either paste the question, or point at a feed item and let its title and summary stand in for it."""

    platform: Literal["reddit", "linkedin", "x"] = "reddit"
    question_text: Question | None = None
    source_url: WebsiteUrl | None = None
    community: Community | None = None
    community_rules: Rules | None = None
    feed_item_id: int | None = None
    instructions: Instructions | None = None

    @model_validator(mode="after")
    def _needs_something_to_reply_to(self):
        if not self.question_text and self.feed_item_id is None:
            raise ValueError("paste the question you want to reply to, or choose a feed item")
        return self


class RedraftRequest(BaseModel):
    instructions: Instructions | None = None


class ReplyUpdate(BaseModel):
    reply_draft: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)] | None = None
    post_idea_title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    post_idea: Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)] | None = None
    status: Literal["open", "posted", "dismissed"] | None = None

    @model_validator(mode="after")
    def _reply_not_null(self):
        for field in ("reply_draft", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ReplyOut(ORM):
    id: int
    venture_id: int
    platform: str
    community: str | None
    source_url: str | None
    feed_item_id: int | None
    question_text: str
    community_rules: str | None
    reply_draft: str
    post_idea_title: str | None
    post_idea: str | None
    notes: str | None
    status: str
    plan_slot_id: int | None
    warnings: list[str] = []
    created_at: datetime
    updated_at: datetime


class ToPlanRequest(BaseModel):
    scheduled_at: AwareDatetime
    platform: Platform
    post_type: PostType = PostType.educational


class ToPlanOut(BaseModel):
    slot_id: int


class OpportunityOut(BaseModel):
    id: int
    title: str
    url: str
    source_label: str
    source_type: str
    engagement: int
    age_hours: float
    score: float
