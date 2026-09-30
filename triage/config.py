"""Settings, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("TRIAGE_LLM_BASE_URL", "https://sluice-orcin.vercel.app/v1")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("TRIAGE_LLM_API_KEY", os.getenv("SLUICE_KEY_TRIAGE", ""))
    )
    llm_model: str = field(default_factory=lambda: os.getenv("TRIAGE_LLM_MODEL", "sluice/smart"))
    redis_url: str = field(default_factory=lambda: os.getenv("UPSTASH_REDIS_REST_URL", ""))
    redis_token: str = field(default_factory=lambda: os.getenv("UPSTASH_REDIS_REST_TOKEN", ""))
    runs_per_hour: int = field(default_factory=lambda: _int("TRIAGE_RUNS_PER_HOUR", 10))
    runs_per_day_total: int = field(default_factory=lambda: _int("TRIAGE_RUNS_PER_DAY", 150))


def get_settings() -> Settings:
    return Settings()
