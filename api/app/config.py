from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "dev-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMM_", extra="ignore", populate_by_name=True)

    env: str = "development"
    database_url: str = "sqlite:///./smm.db"
    secret_key: str = DEFAULT_SECRET
    access_token_minutes: int = 60
    login_max_failures: int = 5  # failed logins per (address, email) before a lockout; 0 disables
    login_window_seconds: int = 900
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    admin_email: str | None = None
    admin_password: str | None = None
    allow_registration: bool = True
    # AI is optional: without a key the suggestion endpoints return 503 and everything else works.
    anthropic_api_key: str | None = Field(default=None, validation_alias=AliasChoices("SMM_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    # Which AI vendor to use: "auto" picks the first one with credentials (Anthropic, then OpenAI, then Gemini).
    ai_provider: Literal["auto", "anthropic", "openai", "gemini"] = "auto"
    # Model id. Defaults to Claude Opus for Anthropic; for OpenAI/Gemini/compatible servers it must be set (model names change too fast to guess).
    ai_model: str | None = None
    # OpenAI, or any OpenAI-compatible server (Groq, Together, OpenRouter, Mistral, DeepSeek, Ollama, vLLM...) via the base URL
    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("SMM_OPENAI_API_KEY", "OPENAI_API_KEY"))
    openai_base_url: str = "https://api.openai.com/v1"
    openai_token_param: str | None = None  # "max_tokens" or "max_completion_tokens"; guessed from the base URL when unset
    gemini_api_key: str | None = Field(default=None, validation_alias=AliasChoices("SMM_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"))
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ai_daily_limit_per_user: int = 20
    # Feed ingestion
    fetch_user_agent: str = "smm-authority/0.1 (+https://github.com/eddytools/smm-authority)"
    allow_private_fetch: bool = False  # tests/dev only: lets the fetcher reach localhost/private networks
    feed_retention_days: int = 30
    refresh_min_interval_seconds: int = 60
    ai_score_batch: int = 20
    # Publishing (LinkedIn / X). Each platform is off until its app credentials are set.
    token_encryption_key: str | None = None  # Fernet key(s); comma-separated to rotate: first encrypts, all decrypt
    public_api_url: str = "http://localhost:8000"  # where the platforms redirect users back to (the OAuth redirect URI host)
    dashboard_url: str = "http://localhost:5173"
    linkedin_client_id: str | None = None
    linkedin_client_secret: str | None = None
    # LinkedIn versions its API by month (YYYYMM) and retires old ones: confirm a current value in LinkedIn's docs.
    linkedin_api_version: str = "202609"
    x_client_id: str | None = None
    x_client_secret: str | None = None
    publish_max_lateness_hours: int = 24

    @property
    def openai_configured(self) -> bool:
        # a self-hosted OpenAI-compatible server (e.g. Ollama) may need no key; the real OpenAI always does
        return bool(self.openai_api_key) or self.openai_base_url.rstrip("/") != "https://api.openai.com/v1"

    @property
    def ai_vendor(self) -> str | None:
        """The vendor that will be used, or None when AI isn't configured."""
        if self.ai_provider != "auto":
            return self.ai_provider
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:  # auto never picks a keyless custom server: choose it explicitly with SMM_AI_PROVIDER=openai
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        return None

    @property
    def effective_ai_model(self) -> str | None:
        return self.ai_model or ("claude-opus-5-5" if self.ai_vendor == "anthropic" else None)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def assert_safe(self) -> None:
        vendor = self.ai_vendor
        if vendor == "anthropic" and not self.anthropic_api_key:
            raise RuntimeError("SMM_AI_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        if vendor == "openai" and not self.openai_configured:
            raise RuntimeError("SMM_AI_PROVIDER=openai needs OPENAI_API_KEY (or SMM_OPENAI_BASE_URL for a self-hosted server)")
        if vendor == "gemini" and not self.gemini_api_key:
            raise RuntimeError("SMM_AI_PROVIDER=gemini needs GEMINI_API_KEY")
        if vendor in ("openai", "gemini") and not self.ai_model:
            raise RuntimeError(f"SMM_AI_MODEL is required with the {vendor} provider (set it to the model id from your vendor's model list)")
        if (self.linkedin_client_id or self.x_client_id) and not self.token_encryption_key:
            raise RuntimeError("SMM_TOKEN_ENCRYPTION_KEY is required when a publishing platform is configured (tokens are never stored in plain text)")
        if self.env == "production" and (self.secret_key == DEFAULT_SECRET or len(self.secret_key) < 32):
            raise RuntimeError("SMM_SECRET_KEY must be set to a random value of at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
