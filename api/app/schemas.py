from datetime import datetime
from typing import Annotated
from urllib.parse import urlparse

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from app.models import Role

Email = Annotated[EmailStr, AfterValidator(lambda v: v.lower())]
Password = Annotated[str, Field(min_length=8, max_length=128)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth / users -----------------------------------------------------------

class RegisterRequest(BaseModel):
    email: Email
    password: Password
    name: Name


class LoginRequest(BaseModel):
    email: Email
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: Role
    is_active: bool
    created_at: datetime


class AdminUserCreate(RegisterRequest):
    role: Role = Role.user


class UserUpdate(BaseModel):
    name: Name | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: Password | None = None


# --- ventures ---------------------------------------------------------------

VentureName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Niche = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


def _check_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc or len(value) > 500:
        raise ValueError("website_url must be a valid http(s) URL up to 500 characters")
    return value.strip()


WebsiteUrl = Annotated[str, AfterValidator(_check_url)]


class VentureCreate(BaseModel):
    name: VentureName
    description: Description | None = None
    niche: Niche | None = None
    website_url: WebsiteUrl | None = None


class VentureUpdate(BaseModel):
    name: VentureName | None = None
    description: Description | None = None
    niche: Niche | None = None
    website_url: WebsiteUrl | None = None
    is_archived: bool | None = None

    @model_validator(mode="after")
    def _required_fields_not_null(self):
        for field in ("name", "is_archived"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class VentureOut(ORM):
    id: int
    owner_id: int
    owner_email: str
    name: str
    description: str | None
    niche: str | None
    website_url: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
