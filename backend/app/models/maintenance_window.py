from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.check import Check
    from app.models.group import Group


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"
    __table_args__ = (
        CheckConstraint(
            "(check_id IS NOT NULL AND group_id IS NULL) OR (check_id IS NULL AND group_id IS NOT NULL)",
            name="ck_maintenance_windows_exactly_one_target",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int | None] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"), nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)

    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    check: Mapped["Check | None"] = relationship(back_populates="maintenance_windows")
    group: Mapped["Group | None"] = relationship(back_populates="maintenance_windows")
