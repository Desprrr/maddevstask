"""Регрессионный тест на находку из DECISIONS.md ("50 проверок... не тормозят
интерфейс"): раньше probe() создавал новый httpx.AsyncClient (= новое
TCP-соединение) на каждый вызов, что под одновременным стартом многих чеков
заметно тормозило и создание чеков, и API. Общий клиент на процесс — часть
контракта модуля, а не деталь реализации, которую можно случайно откатить."""

import pytest

from app.scheduler import prober

pytestmark = pytest.mark.asyncio


async def test_shared_http_client_is_reused_across_calls() -> None:
    await prober.close_shared_client()  # чистое состояние на случай другого теста до этого
    try:
        client1 = prober._get_client()
        client2 = prober._get_client()
        assert client1 is client2
    finally:
        await prober.close_shared_client()


async def test_close_shared_client_forces_a_fresh_one_afterwards() -> None:
    await prober.close_shared_client()
    try:
        client1 = prober._get_client()
        await prober.close_shared_client()
        client2 = prober._get_client()
        assert client1 is not client2
    finally:
        await prober.close_shared_client()
