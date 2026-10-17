from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "dev-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMM_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./smm.db"
    secret_key: str = DEFAULT_SECRET
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:5173"
    admin_email: str | None = None
    admin_password: str | None = None
    allow_registration: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def assert_safe(self) -> None:
        if self.env == "production" and (self.secret_key == DEFAULT_SECRET or len(self.secret_key) < 32):
            raise RuntimeError("SMM_SECRET_KEY must be set to a random value of at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
