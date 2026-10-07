from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    google_api_key: SecretStr = SecretStr("")
    llm_model: str = "gemini-2.0-flash"
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "https://cloud.langfuse.com"

    database_url: str = "sqlite:///./data/shop.db"
    max_sql_retries: int = Field(default=3, ge=0, le=10)
    max_rows: int = Field(default=100, ge=1, le=1000)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()