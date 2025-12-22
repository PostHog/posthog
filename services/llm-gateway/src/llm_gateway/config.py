from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    debug: bool = False

    database_url: str = "postgres://posthog:posthog@localhost:5432/posthog"
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    redis_url: str | None = None

    rate_limit_burst: int = 500
    rate_limit_burst_window: int = 60
    rate_limit_sustained: int = 10000
    rate_limit_sustained_window: int = 3600

    request_timeout: float = 300.0
    streaming_timeout: float = 300.0

    max_request_body_size: int = 10_485_760  # 10MB

    cors_origins: list[str] = ["*"]

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_api_base_url: str | None = None  # Used for regional endpoints
    gemini_api_key: str | None = None

    # Used to send gateway errors to error tracking
    posthog_api_key: str | None = None

    metrics_enabled: bool = True

    # ~600 bytes per entry (key + AuthenticatedUser + LRU overhead), 10000 entries ≈ 6 MB
    auth_cache_max_size: int = 10000
    auth_cache_ttl: int = 900  # 15 minutes

    model_config = {"env_prefix": "LLM_GATEWAY_"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
