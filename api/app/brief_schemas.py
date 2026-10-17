"""Authority Brief: the one-time setup captured per venture (PRD F2, F3)."""

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.schemas import ORM, WebsiteUrl

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]
Item = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Sample = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]
Items = Annotated[list[Item], Field(max_length=15)]


class Platform(str, Enum):
    linkedin = "linkedin"
    x = "x"
    reddit = "reddit"
    instagram = "instagram"
    youtube = "youtube"
    blog = "blog"
    newsletter = "newsletter"


class ICP(BaseModel):
    industry: Text | None = None
    company_size: Text | None = None
    roles: Items = []
    pains: Items = []
    goals: Items = []
    objections: Items = []
    channels: Items = []  # where the ICP spends time


class Ideation(BaseModel):
    niche_statement: Text | None = None
    unique_angle: Text | None = None
    pillars: Annotated[list[Item], Field(max_length=5)] = []
    proof_assets: Items = []
    opinions: Items = []


class Offer(BaseModel):
    offer: Text | None = None
    lead_magnets: Items = []
    cta_url: WebsiteUrl | None = None
    booking_url: WebsiteUrl | None = None


class Voice(BaseModel):
    tone: Text | None = None
    dos: Items = []
    donts: Items = []
    writing_samples: Annotated[list[Sample], Field(max_length=5)] = []


class PlatformPlan(BaseModel):
    platform: Platform
    cadence_per_week: Annotated[int, Field(ge=1, le=21)] = 3
    is_primary: bool = False
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)] | None = None


class BriefData(BaseModel):
    icp: ICP = ICP()
    ideation: Ideation = Ideation()
    offer: Offer = Offer()
    voice: Voice = Voice()
    platforms: Annotated[list[PlatformPlan], Field(max_length=len(Platform))] = []

    @field_validator("platforms")
    @classmethod
    def _valid_platforms(cls, plans: list[PlatformPlan]) -> list[PlatformPlan]:
        if len({p.platform for p in plans}) != len(plans):
            raise ValueError("each platform can only be listed once")
        if sum(p.is_primary for p in plans) > 1:
            raise ValueError("only one platform can be primary")
        return plans


class BriefOut(ORM):
    venture_id: int
    version: int
    data: BriefData
    created_by_id: int | None
    created_at: datetime


class BriefVersionSummary(ORM):
    version: int
    created_by_id: int | None
    created_at: datetime


class SuggestRequest(BaseModel):
    """What the user has told us so far. Everything is optional; the venture's own fields are always included."""

    icp: ICP = ICP()
    offer: Offer = Offer()
    voice: Voice = Voice()
    ideation: Ideation = Ideation()  # existing answers the model should respect rather than overwrite


class BriefSuggestion(BaseModel):
    ideation: Ideation
    platforms: list[PlatformPlan]
    rationale: str

