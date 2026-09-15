from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.models.check import Check

# Общий клиент на все пробы вместо нового httpx.AsyncClient (и нового
# TCP-соединения) на каждый вызов — важно под требование "50 проверок не
# мешают друг другу и не тормозят интерфейс": httpx.AsyncClient потокобезопасен
# для конкурентного использования и держит пул keep-alive соединений.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        )
    return _client


async def close_shared_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


@dataclass
class ProbeOutcome:
    success: bool
    response_time_ms: int | None
    status_code: int | None
    error: str | None


async def probe(check: Check) -> ProbeOutcome:
    """Выполняет одну HTTP-пробу. Никогда не бросает исключение наружу —
    сетевые ошибки/таймауты превращаются в ProbeOutcome(success=False, ...)."""
    started = time.monotonic()
    timeout = httpx.Timeout(check.timeout_ms / 1000)

    try:
        response = await _get_client().get(check.url, timeout=timeout)
    except httpx.TimeoutException:
        return ProbeOutcome(success=False, response_time_ms=None, status_code=None, error="timeout")
    except httpx.HTTPError as exc:
        return ProbeOutcome(success=False, response_time_ms=None, status_code=None, error=str(exc))

    elapsed_ms = int((time.monotonic() - started) * 1000)

    problems: list[str] = []
    if response.status_code != check.expected_status_code:
        problems.append(f"status {response.status_code} != expected {check.expected_status_code}")
    if check.expected_body_substring and check.expected_body_substring not in response.text:
        problems.append("expected body substring not found")

    return ProbeOutcome(
        success=not problems,
        response_time_ms=elapsed_ms,
        status_code=response.status_code,
        error="; ".join(problems) or None,
    )
