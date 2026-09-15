from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.models.check import Check


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
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(check.url)
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
