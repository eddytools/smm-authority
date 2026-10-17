from datetime import date, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

from app.brief_schemas import Platform
from app.framework import DEFAULT_MIX, PostType, SlotStatus, Stage
from app.schemas import ORM

Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Cta = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Draft = Annotated[str, StringConstraints(max_length=10000)]


class Mix(BaseModel):
    tofu: Annotated[int, Field(ge=0, le=100)] = DEFAULT_MIX["tofu"]
    mofu: Annotated[int, Field(ge=0, le=100)] = DEFAULT_MIX["mofu"]
    bofu: Annotated[int, Field(ge=0, le=100)] = DEFAULT_MIX["bofu"]

    @model_validator(mode="after")
    def _sums_to_100(self):
        if self.tofu + self.mofu + self.bofu != 100:
            raise ValueError("funnel mix must add up to 100")
        return self


class GenerateRequest(BaseModel):
    start_date: date
    period: Literal["week", "month"] = "month"
    timezone: str = "UTC"
    mix: Mix = Mix()
    replace: bool = False

    @model_validator(mode="after")
    def _check(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError("unknown timezone, use an IANA name like 'Europe/London'")
        today = date.today()
        if not (today - timedelta(days=7) <= self.start_date <= today + timedelta(days=366)):
            raise ValueError("start_date must be within the next year (or the last week)")
        return self


class GenerateOut(BaseModel):
    created: int
    removed: int
    kept: int
    by_stage: dict[str, int]


class SlotCreate(BaseModel):
    scheduled_at: AwareDatetime
    platform: Platform
    post_type: PostType
    topic: Topic
    pillar: Short | None = None
    cta: Cta | None = None


class SlotUpdate(BaseModel):
    scheduled_at: AwareDatetime | None = None
    platform: Platform | None = None
    post_type: PostType | None = None
    topic: Topic | None = None
    pillar: Short | None = None
    cta: Cta | None = None
    draft: Draft | None = None
    status: SlotStatus | None = None
    locked: bool | None = None

    @model_validator(mode="after")
    def _required_not_null(self):
        for field in ("scheduled_at", "platform", "post_type", "topic", "status", "locked"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SlotOut(ORM):
    id: int
    venture_id: int
    scheduled_at: AwareDatetime
    platform: str
    post_type: PostType
    stage: Stage
    pillar: str | None
    topic: str
    cta: str | None
    draft: str | None
    status: SlotStatus
    locked: bool
    reactive: bool
    source_item_id: int | None
    warnings: list[str] = []


class DraftRequest(BaseModel):
    instructions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class DraftOut(BaseModel):
    draft: str
    hooks: list[str]
    notes: str
    warnings: list[str]
