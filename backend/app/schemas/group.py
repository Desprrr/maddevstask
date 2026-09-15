from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_public: bool = False
    alert_emails: list[EmailStr] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_public: bool | None = None
    alert_emails: list[EmailStr] | None = None


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_public: bool
    created_at: dt.datetime
    alert_emails: list[str] = Field(default_factory=list)
