from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel


class PublicCheckStatus(BaseModel):
    check_id: int
    name: str
    status: Literal["up", "down"]
    last_checked_at: dt.datetime | None
    current_downtime_seconds: int | None
    uptime_ratio_24h: float | None


class PublicGroupStatus(BaseModel):
    group_id: int | None
    name: str | None  # None — чеки без группы
    status: Literal["up", "down"]
    checks: list[PublicCheckStatus]


class PublicStatusOut(BaseModel):
    groups: list[PublicGroupStatus]
