from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaintenanceWindowCreate(BaseModel):
    check_id: int | None = None
    group_id: int | None = None
    starts_at: dt.datetime
    ends_at: dt.datetime
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "MaintenanceWindowCreate":
        if (self.check_id is None) == (self.group_id is None):
            raise ValueError("exactly one of check_id or group_id must be set")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class MaintenanceWindowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    check_id: int | None
    group_id: int | None
    starts_at: dt.datetime
    ends_at: dt.datetime
    note: str | None
