from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import checks, groups
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Site Availability Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(groups.router, prefix="/api")
app.include_router(checks.router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
