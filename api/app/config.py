from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "dev-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMM_", extra="ignore", populate_by_name=True)

    env: str = "development"
    database_url: str = "sqlite:///./smm.db"
    secret_key: str = DEFAULT_SECRET
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    admin_email: str | None = None
    admin_password: str | None = None
    allow_registration: bool = True
    # AI is optional: without a key the suggestion endpoints return 503 and everything else works.
    anthropic_api_key: str | None = Field(default=None, validation_alias=AliasChoices("SMM_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    ai_model: str = "claude-opus-5-5"
    ai_daily_limit_per_user: int = 20
    # Feed ingestion
    fetch_user_agent: str = "smm-authority/0.1 (+https://github.com/eddytools/smm-authority)"
    allow_private_fetch: bool = False  # tests/dev only: lets the fetcher reach localhost/private networks
    feed_retention_days: int = 30
    refresh_min_interval_seconds: int = 60
    ai_score_batch: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def assert_safe(self) -> None:
        if self.env == "production" and (self.secret_key == DEFAULT_SECRET or len(self.secret_key) < 32):
            raise RuntimeError("SMM_SECRET_KEY must be set to a random value of at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
