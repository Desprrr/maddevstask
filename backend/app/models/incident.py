from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.check import Check

END_RECOVERED = "recovered"
END_MONITORING_GAP = "monitoring_gap"
END_PAUSED = "paused"


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_check_id_started_at", "check_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"))

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    alert_down_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_recovered_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Инцидент закрылся, так никому и не став известным, и сообщать о нём не нужно
    # (прошёл внутри окна обслуживания или прерван, а не восстановился).
    notifications_skipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    check: Mapped["Check"] = relationship(back_populates="incidents")

    @property
    def is_open(self) -> bool:
        return self.ended_at is None
