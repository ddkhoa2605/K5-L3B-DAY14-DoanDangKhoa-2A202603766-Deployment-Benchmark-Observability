"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Không có secret nào nằm trong code: AGENT_API_KEY phải được cấp qua env (xem .env.example).
"""
import os
from dataclasses import dataclass, field


def _str(name: str, default: str) -> str:
    return os.getenv(name) or default


def _int(name: str, default: int) -> int:
    return int(os.getenv(name) or default)


def _float(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: _int("PORT", 8000))
    environment: str = field(default_factory=lambda: _str("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: _str("LOG_LEVEL", "INFO").upper())
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: _str("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _float("MONTHLY_BUDGET_USD", 30.0))

    def validate(self) -> "Settings":
        if self.environment == "production" and not self.agent_api_key:
            raise ValueError("AGENT_API_KEY must be set when ENVIRONMENT=production")
        return self


settings = Settings().validate()
