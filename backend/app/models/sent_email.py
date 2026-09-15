from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SentEmail(Base):
    __tablename__ = "sent_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    to_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    backend: Mapped[str] = mapped_column(String(10))
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
