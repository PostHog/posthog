import json
from functools import lru_cache

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings


class ProductCostLimit(BaseModel, frozen=True):
    limit_usd: float
    window_seconds: int


class UserCostLimit(BaseModel, frozen=True):
    burst_limit_usd: float
    burst_window_seconds: int
    sustained_limit_usd: float
    sustained_window_seconds: int


DEFAULT_USER_COST_LIMIT = UserCostLimit(
    burst_limit_usd=100.0,
    burst_window_seconds=86400,
    sustained_limit_usd=1000.0,
    sustained_window_seconds=2592000,
)

DEFAULT_PRODUCT_COST_LIMITS: dict[str, "ProductCostLimit"] = {
    "llm_gateway": ProductCostLimit(limit_usd=1000.0, window_seconds=86400),
    "wizard": ProductCostLimit(limit_usd=2000.0, window_seconds=86400),
    "twig": ProductCostLimit(limit_usd=1000.0, window_seconds=3600),
    "background_agents": ProductCostLimit(limit_usd=1000.0, window_seconds=3600),
}

DEFAULT_USER_COST_LIMITS: dict[str, "UserCostLimit"] = {
    "twig": UserCostLimit(
        burst_limit_usd=100.0,
        burst_window_seconds=86400,
        sustained_limit_usd=1000.0,
        sustained_window_seconds=2592000,
    ),
    "background_agents": UserCostLimit(
        burst_limit_usd=100.0,
        burst_window_seconds=86400,
        sustained_limit_usd=1000.0,
        sustained_window_seconds=2592000,
    ),
}


def _parse_model_dict(
    v: str | dict | None,
    model_cls: type[BaseModel],
    default: dict,
    field_name: str,
) -> dict:
    if v is None or v == "":
        return default
    if isinstance(v, dict):
        result = {}
        for key, config in v.items():
            if isinstance(config, model_cls):
                result[key] = config
            elif isinstance(config, dict):
                result[key] = model_cls(**config)
            else:
                raise ValueError(f"Invalid config for {key}")
        return result
    try:
        parsed = json.loads(v)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {field_name}: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return {key: model_cls(**config) for key, config in parsed.items()}


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

    # Project token for LLM analytics events
    posthog_project_token: str | None = None
    posthog_host: str = "https://us.i.posthog.com"

    metrics_enabled: bool = True

    # ~600 bytes per entry (key + AuthenticatedUser + LRU overhead), 10000 entries ≈ 6 MB
    auth_cache_max_size: int = 10000
    auth_cache_ttl: int = 900  # 15 minutes — used for personal API keys
    auth_cache_ttl_oauth: int = 300  # 5 minutes — OAuth tokens can be revoked on refresh, keep short

    team_rate_limit_multipliers: dict[int, int] = {}

    product_cost_limits: dict[str, ProductCostLimit] = DEFAULT_PRODUCT_COST_LIMITS

    user_cost_limits: dict[str, UserCostLimit] = DEFAULT_USER_COST_LIMITS
    user_cost_limits_disabled: bool = False

    default_fallback_cost_usd: float = 0.01

    @field_validator("product_cost_limits", mode="before")
    @classmethod
    def parse_product_cost_limits(cls, v: str | dict | None) -> dict[str, ProductCostLimit]:
        return _parse_model_dict(v, ProductCostLimit, DEFAULT_PRODUCT_COST_LIMITS, "product_cost_limits")

    @field_validator("user_cost_limits", mode="before")
    @classmethod
    def parse_user_cost_limits(cls, v: str | dict | None) -> dict[str, UserCostLimit]:
        return _parse_model_dict(v, UserCostLimit, DEFAULT_USER_COST_LIMITS, "user_cost_limits")

    @field_validator("team_rate_limit_multipliers", mode="before")
    @classmethod
    def parse_team_multipliers(cls, v: str | dict[int, int] | None) -> dict[int, int]:
        if v is None or v == "":
            return {}
        if isinstance(v, dict):
            return v
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in team_rate_limit_multipliers: {e}") from e

        if not isinstance(parsed, dict):
            raise ValueError("team_rate_limit_multipliers must be a JSON object")

        try:
            result = {int(k): int(val) for k, val in parsed.items()}
        except (ValueError, TypeError) as e:
            raise ValueError(f"team_rate_limit_multipliers keys and values must be integers: {e}") from e

        for team_id, multiplier in result.items():
            if multiplier < 1:
                raise ValueError(
                    f"team_rate_limit_multipliers values must be >= 1, got {multiplier} for team {team_id}"
                )

        return result

    model_config = {"env_prefix": "LLM_GATEWAY_"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
