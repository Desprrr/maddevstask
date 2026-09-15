from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from email.message import EmailMessage

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.models.sent_email import SentEmail

logger = logging.getLogger(__name__)


class EmailSender(ABC):
    @abstractmethod
    async def send(self, to: str, subject: str, body: str) -> None: ...


class _RecordingMixin:
    """Обе реализации пишут в sent_emails — это единый outbox, по которому
    видно, что письмо действительно "отправлено" (доказуемость), независимо
    от того, ушло оно по-настоящему по SMTP или это локальная заглушка."""

    _session_factory: async_sessionmaker
    _backend_name: str

    async def _record(self, to: str, subject: str, body: str) -> None:
        async with self._session_factory() as db:
            db.add(SentEmail(to_email=to, subject=subject, body=body, backend=self._backend_name))
            await db.commit()


class FakeEmailSender(_RecordingMixin, EmailSender):
    """Никуда не отправляет по-настоящему — только лог + запись в sent_emails.
    Используется по умолчанию для локальной разработки без почтового сервера."""

    _backend_name = "fake"

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def send(self, to: str, subject: str, body: str) -> None:
        logger.info("FAKE EMAIL to=%s subject=%r", to, subject)
        await self._record(to, subject, body)


class SmtpEmailSender(_RecordingMixin, EmailSender):
    """Реальная отправка по SMTP — рассчитана на Mailpit из docker-compose,
    но подойдёт для любого SMTP-сервера."""

    _backend_name = "smtp"

    def __init__(self, session_factory: async_sessionmaker, host: str, port: int, sender: str) -> None:
        self._session_factory = session_factory
        self._host = host
        self._port = port
        self._sender = sender

    async def send(self, to: str, subject: str, body: str) -> None:
        import aiosmtplib

        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        await aiosmtplib.send(message, hostname=self._host, port=self._port)
        await self._record(to, subject, body)


def make_email_sender(settings: Settings, session_factory: async_sessionmaker) -> EmailSender:
    if settings.email_backend == "smtp":
        return SmtpEmailSender(session_factory, settings.smtp_host, settings.smtp_port, settings.smtp_from)
    return FakeEmailSender(session_factory)
