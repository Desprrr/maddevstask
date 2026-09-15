import asyncio
import random

from fastapi import FastAPI, Response

app = FastAPI(title="Target Emulator")


@app.get("/")
async def index() -> dict[str, list[str]]:
    return {
        "endpoints": [
            "/ok",
            "/status/{code}",
            "/delay/{ms}",
            "/timeout",
            "/flaky/{fail_rate}",
        ]
    }


@app.get("/ok")
async def ok() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status/{code}")
async def status(code: int, response: Response) -> dict[str, int]:
    response.status_code = max(100, min(code, 599))
    return {"status": response.status_code}


@app.get("/delay/{ms}")
async def delay(ms: int) -> dict[str, int]:
    await asyncio.sleep(max(0, min(ms, 120_000)) / 1000)
    return {"delayed_ms": ms}


@app.get("/timeout")
async def timeout() -> dict[str, str]:
    # Дольше любого разумного timeout проверки — эмулирует зависшую цель.
    await asyncio.sleep(3600)
    return {"status": "unreachable"}  # практически никогда не вернётся


@app.get("/flaky/{fail_rate}")
async def flaky(fail_rate: int, response: Response) -> dict[str, str]:
    if random.random() * 100 < max(0, min(fail_rate, 100)):
        response.status_code = 500
        return {"status": "error"}
    return {"status": "ok"}
