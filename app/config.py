from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    openai_api_key: str
    openai_model: str = Field(default="gpt-4.1-mini")
    openai_timeout_seconds: float = Field(default=30.0)
    recent_user_messages: int = Field(default=10)
    database_url: str = Field(
        description="SQLAlchemy URL для PostgreSQL, например postgresql+asyncpg://user:pass@host:5432/db",
    )
    admin_telegram_ids: str = Field(
        default="",
        description="Список Telegram user id админов через запятую (env: ADMIN_TELEGRAM_IDS)",
    )

    # Платёжный провайдер: stripe (по умолчанию, есть sandbox) или yookassa
    payment_provider: Literal["stripe", "yookassa"] = Field(default="stripe")
    payment_return_url: str = Field(default="https://t.me/your_bot")

    # Stripe
    stripe_secret_key: str = Field(default="")
    stripe_webhook_secret: str = Field(default="")

    # ЮKassa
    yookassa_shop_id: str = Field(default="")
    yookassa_secret_key: str = Field(default="")

    # Веб-сервис (FastAPI)
    web_host: str = Field(default="0.0.0.0")
    web_port: int = Field(default=8000)
    admin_web_username: str = Field(default="admin")
    admin_web_password: str = Field(default="changeme")

    def get_admin_ids(self) -> frozenset[int]:
        if not self.admin_telegram_ids.strip():
            return frozenset()
        out: list[int] = []
        for part in self.admin_telegram_ids.split(","):
            p = part.strip()
            if p.isdigit():
                out.append(int(p))
        return frozenset(out)

    @property
    def payments_configured(self) -> bool:
        if self.payment_provider == "stripe":
            return bool(self.stripe_secret_key)
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)


class DbSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        description="SQLAlchemy URL для PostgreSQL, например postgresql+asyncpg://user:pass@host:5432/db",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_database_url() -> str:
    return DbSettings().database_url
