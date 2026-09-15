from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://monitor:monitor@localhost:5432/monitor"

    email_backend: str = "fake"  # "fake" | "smtp"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "monitor@example.com"

    cors_origins: list[str] = ["http://localhost:5173"]

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
