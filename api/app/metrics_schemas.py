from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas import ORM

Count = Annotated[int, Field(ge=0, le=1_000_000_000)]


class MetricsIn(BaseModel):
    impressions: Count = 0
    reactions: Count = 0
    comments: Count = 0
    shares: Count = 0
    saves: Count = 0
    clicks: Count = 0
    follows: Count = 0
    leads: Count = 0


class MetricsOut(ORM):
    slot_id: int
    impressions: int
    reactions: int
    comments: int
    shares: int
    saves: int
    clicks: int
    follows: int
    leads: int
    source: str
    updated_at: datetime


class ImportRequest(BaseModel):
    csv: Annotated[str, StringConstraints(min_length=1, max_length=1_000_000)]


class ImportError_(BaseModel):
    row: int
    message: str


class ImportOut(BaseModel):
    imported: int
    errors: list[ImportError_]
