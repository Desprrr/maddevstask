from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.check_result import CheckResult
    from app.models.group import Group
    from app.models.incident import Incident
    from app.models.maintenance_window import MaintenanceWindow


class Check(Base):
    __tablename__ = "checks"
    __table_args__ = (
        CheckConstraint("interval_seconds BETWEEN 30 AND 3600", name="ck_checks_interval_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)

    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2048))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=5000)
    expected_status_code: Mapped[int] = mapped_column(Integer, default=200)
    expected_body_substring: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Получателям отправлено DOWN, а RECOVERED ещё нет. Отделено от инцидентов:
    # простой мониторинга может разрезать одно падение на два инцидента в журнале,
    # но для получателей это всё ещё одно падение — одно DOWN и одно RECOVERED.
    down_notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    group: Mapped["Group | None"] = relationship(back_populates="checks")
    results: Mapped[list["CheckResult"]] = relationship(back_populates="check", cascade="all, delete-orphan")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="check", cascade="all, delete-orphan")
    maintenance_windows: Mapped[list["MaintenanceWindow"]] = relationship(
        back_populates="check", cascade="all, delete-orphan"
    )
