from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class CheckCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    group_id: int | None = None
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    timeout_ms: int = Field(default=5000, gt=0, le=120_000)
    expected_status_code: int = Field(default=200, ge=100, le=599)
    expected_body_substring: str | None = Field(default=None, max_length=500)
    is_public: bool = False


class CheckUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    group_id: int | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=3600)
    timeout_ms: int | None = Field(default=None, gt=0, le=120_000)
    expected_status_code: int | None = Field(default=None, ge=100, le=599)
    expected_body_substring: str | None = Field(default=None, max_length=500)
    is_public: bool | None = None


class CheckResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    check_id: int
    checked_at: dt.datetime
    success: bool
    response_time_ms: int | None
    status_code: int | None
    error: str | None


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    group_id: int | None
    interval_seconds: int
    timeout_ms: int
    expected_status_code: int
    expected_body_substring: str | None
    is_paused: bool
    is_public: bool
    created_at: dt.datetime
    updated_at: dt.datetime
