from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTSCOPE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agentscope:agentscope@127.0.0.1:55432/agentscope"
    artifact_root: Path = Path("artifacts")
    sandbox_image: str = "agentscope-sandbox:py312"
    max_concurrent_runs: int = Field(default=2, ge=1, le=64)
    log_level: str = "INFO"
    api_key: str | None = None
    api_token: str | None = None
    max_request_bytes: int = Field(default=1_048_576, ge=1)
    provider_max_attempts: int = Field(default=4, ge=1, le=10)
    provider_backoff_base_seconds: float = Field(default=0.5, ge=0)
    provider_backoff_cap_seconds: float = Field(default=30.0, ge=0)
    agent_max_tool_calls: int = Field(default=200, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
