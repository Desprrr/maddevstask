from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class IncidentOut(BaseModel):
    id: int
    check_id: int
    started_at: dt.datetime
    ended_at: dt.datetime | None
    duration_seconds: int | None
