from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "Infinity Company API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+asyncpg://infinity:infinity_dev_password@localhost:5432/infinity"
    )
    jwt_secret: SecretStr = Field(min_length=32)
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    payment_provider: str = "mock"
    payment_currency: str = "EGP"
    paymob_api_base_url: str = "https://accept.paymob.com"
    paymob_checkout_base_url: str = "https://eg.checkout.paymob.com/"
    paymob_secret_key: SecretStr | None = None
    paymob_public_key: SecretStr | None = None
    paymob_card_integration_id: int | None = None
    paymob_hmac_secret: SecretStr | None = None
    paymob_notification_url: str | None = None
    payment_token_encryption_key: SecretStr | None = None
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
