"""Демо-данные для быстрого запуска "из коробки": группа с несколькими
чеками, указывающими на target-emulator, чтобы сразу было видно живую
работу монитора (успех/ошибка/таймаут/нестабильность), а не пустой экран.

Запуск: `python -m app.seed` (из backend/, с активным venv). URL
target-emulator берётся из TARGET_EMULATOR_BASE_URL (по умолчанию
http://localhost:9100 — для docker-compose переопределяется на
http://target-emulator:9100, см. docker-compose.yml).

Идемпотентно: если хоть одна группа уже есть в БД, ничего не делает —
безопасно звать повторно (например, при каждом старте контейнера).
"""

import asyncio
import os

from sqlalchemy import select

from app.db import async_session_factory
from app.models.check import Check
from app.models.group import Group, GroupAlertEmail

TARGET_BASE = os.environ.get("TARGET_EMULATOR_BASE_URL", "http://localhost:9100")


async def seed() -> None:
    async with async_session_factory() as db:
        existing = (await db.execute(select(Group.id).limit(1))).first()
        if existing is not None:
            print("Seed: данные уже есть, пропускаю.")
            return

        group = Group(name="Demo")
        group.alert_emails = [GroupAlertEmail(email="demo@example.com")]
        db.add(group)
        await db.flush()

        db.add_all(
            [
                Check(
                    name="Emulator: OK",
                    url=f"{TARGET_BASE}/ok",
                    group_id=group.id,
                    interval_seconds=30,
                    timeout_ms=3000,
                    expected_status_code=200,
                    expected_body_substring="ok",
                    is_public=True,
                ),
                Check(
                    name="Emulator: медленный, но живой",
                    url=f"{TARGET_BASE}/delay/2000",
                    group_id=group.id,
                    interval_seconds=30,
                    timeout_ms=5000,
                    expected_status_code=200,
                    is_public=True,
                ),
                Check(
                    name="Emulator: неверный статус",
                    url=f"{TARGET_BASE}/status/500",
                    group_id=group.id,
                    interval_seconds=30,
                    timeout_ms=3000,
                    expected_status_code=200,
                    is_public=True,
                ),
                Check(
                    name="Emulator: нестабильный",
                    url=f"{TARGET_BASE}/flaky/40",
                    group_id=group.id,
                    interval_seconds=30,
                    timeout_ms=3000,
                    expected_status_code=200,
                    is_public=True,
                ),
                Check(
                    name="Emulator: не отвечает",
                    url=f"{TARGET_BASE}/timeout",
                    group_id=group.id,
                    interval_seconds=30,
                    timeout_ms=2000,
                    expected_status_code=200,
                    is_public=False,
                ),
            ]
        )
        await db.commit()

    print("Seed: создана группа Demo с 5 проверками на target-emulator.")


if __name__ == "__main__":
    asyncio.run(seed())
