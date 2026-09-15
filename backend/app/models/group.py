from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.check import Check
    from app.models.maintenance_window import MaintenanceWindow


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    checks: Mapped[list["Check"]] = relationship(back_populates="group")
    alert_emails: Mapped[list["GroupAlertEmail"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    maintenance_windows: Mapped[list["MaintenanceWindow"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupAlertEmail(Base):
    __tablename__ = "group_alert_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))

    group: Mapped["Group"] = relationship(back_populates="alert_emails")
