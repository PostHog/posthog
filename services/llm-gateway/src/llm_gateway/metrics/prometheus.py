from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

from llm_gateway.metrics.topk import TopKCounter

REQUEST_COUNT = Counter(
    "llm_gateway_requests_total",
    "Total LLM Gateway requests",
    labelnames=["endpoint", "provider", "model", "status_code", "auth_method", "product"],
)

REQUEST_LATENCY = Histogram(
    "llm_gateway_request_duration_seconds",
    "Request latency",
    labelnames=["endpoint", "provider", "streaming", "product"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

TOKENS_INPUT = Counter(
    "llm_gateway_tokens_input_total",
    "Total input tokens",
    labelnames=["provider", "model", "product"],
)

TOKENS_OUTPUT = Counter(
    "llm_gateway_tokens_output_total",
    "Total output tokens",
    labelnames=["provider", "model", "product"],
)

TOKENS_CACHE_READ = Counter(
    "llm_gateway_tokens_cache_read_total",
    "Total cached input tokens (cache hits)",
    labelnames=["provider", "model", "product"],
)

TOKENS_CACHE_CREATION = Counter(
    "llm_gateway_tokens_cache_creation_total",
    "Total cache creation input tokens (cache writes)",
    labelnames=["provider", "model", "product"],
)

TOKENS_REASONING = Counter(
    "llm_gateway_tokens_reasoning_total",
    "Total reasoning tokens (for reasoning models)",
    labelnames=["provider", "model", "product"],
)

COST_USD = Counter(
    "llm_gateway_cost_usd_total",
    "Total cost in USD",
    labelnames=["provider", "model", "product"],
)

COST_INPUT_USD = Counter(
    "llm_gateway_cost_input_usd_total",
    "Total input cost in USD",
    labelnames=["provider", "model", "product"],
)

COST_OUTPUT_USD = Counter(
    "llm_gateway_cost_output_usd_total",
    "Total output cost in USD",
    labelnames=["provider", "model", "product"],
)

COST_CACHE_SAVINGS_USD = Counter(
    "llm_gateway_cost_cache_savings_usd_total",
    "Total cost saved from caching in USD",
    labelnames=["provider", "model", "product"],
)

LLM_RESPONSE_TIME = Histogram(
    "llm_gateway_llm_response_time_seconds",
    "Total LLM response time (provider latency)",
    labelnames=["provider", "model", "product"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

LLM_TIME_TO_FIRST_TOKEN = Histogram(
    "llm_gateway_llm_ttft_seconds",
    "Time to first token for streaming requests",
    labelnames=["provider", "model", "product"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

LLM_REQUESTS = Counter(
    "llm_gateway_llm_requests_total",
    "Total LLM requests by type",
    labelnames=["provider", "model", "product", "streaming"],
)

COST_BY_TEAM_USD = TopKCounter(
    name="llm_gateway_cost_by_team_usd",
    documentation="Total cost in USD by team (top 100 only)",
    k=100,
)

RATE_LIMIT_EXCEEDED = Counter(
    "llm_gateway_rate_limit_exceeded_total",
    "Rate limit exceeded events",
    labelnames=["scope"],
)

PRODUCT_COST_WINDOW_USD = Gauge(
    "llm_gateway_product_cost_window_usd",
    (
        "Current accumulated cost (USD) for a product within its configured window. "
        "Reflects only the shared pool — spend from teams with a team_rate_limit_multipliers "
        "override lives in a separate per-multiplier Redis bucket and is not included here."
    ),
    labelnames=["product"],
)

PRODUCT_COST_LIMIT_USD = Gauge(
    "llm_gateway_product_cost_limit_usd",
    (
        "Configured cost cap (USD) for a product within its configured window. "
        "This is the base (team_mult=1) cap that pairs with llm_gateway_product_cost_window_usd; "
        "teams with a team_rate_limit_multipliers override get a multiplied cap not reflected here."
    ),
    labelnames=["product"],
)

PRODUCT_COST_WINDOW_SECONDS = Gauge(
    "llm_gateway_product_cost_window_seconds",
    (
        "Remaining seconds until the shared-pool cost window resets for a product (Redis TTL of the "
        "shared-pool counter; falls back to the configured window length when no spend has been recorded)."
    ),
    labelnames=["product"],
)

PROVIDER_ERRORS = Counter(
    "llm_gateway_provider_errors_total",
    "Provider API errors",
    labelnames=["provider", "error_type", "product"],
)

ACTIVE_STREAMS = Gauge(
    "llm_gateway_active_streams",
    "Currently active streaming connections",
    labelnames=["provider", "model", "product"],
)

DB_POOL_SIZE = Gauge(
    "llm_gateway_db_pool_size",
    "Database connection pool size",
    labelnames=["state"],
)

AUTH_CACHE_HITS = Counter(
    "llm_gateway_auth_cache_hits_total",
    "Auth cache hits",
    labelnames=["auth_type"],
)

AUTH_CACHE_MISSES = Counter(
    "llm_gateway_auth_cache_misses_total",
    "Auth cache misses",
    labelnames=["auth_type"],
)

AUTH_INVALID = Counter(
    "llm_gateway_auth_invalid_total",
    "Invalid authentication attempts",
    labelnames=["auth_type"],
)

REDIS_FALLBACK = Counter(
    "llm_gateway_redis_fallback_total",
    "Redis rate limiter fallback events",
)

STREAMING_CLIENT_DISCONNECT = Counter(
    "llm_gateway_streaming_client_disconnect_total",
    "Client disconnected during streaming",
    labelnames=["provider", "model", "product"],
)

CONCURRENT_REQUESTS = Gauge(
    "llm_gateway_concurrent_requests",
    "Current in-flight requests",
    labelnames=["provider", "model", "product"],
)

DB_POOL_EXHAUSTED = Counter(
    "llm_gateway_db_pool_exhausted_total",
    "Database pool exhaustion events",
)

CALLBACK_SUCCESS = Counter(
    "llm_gateway_callback_success_total",
    "Callback successful executions",
    labelnames=["callback"],
)

CALLBACK_ERRORS = Counter(
    "llm_gateway_callback_errors_total",
    "Callback errors",
    labelnames=["callback", "error_type"],
)

COST_RECORDED = Counter(
    "llm_gateway_cost_recorded_total",
    "Total cost (USD) recorded for rate limiting",
    labelnames=["provider", "model", "product"],
)

COST_ESTIMATED = Counter(
    "llm_gateway_cost_estimated_total",
    "Requests where cost was estimated from tokens",
    labelnames=["provider", "model", "product"],
)

COST_MISSING = Counter(
    "llm_gateway_cost_missing_total",
    "Requests where cost was not available",
    labelnames=["provider", "model", "product"],
)

COST_FALLBACK_DEFAULT = Counter(
    "llm_gateway_cost_fallback_default_total",
    "Requests where default fallback cost was used",
    labelnames=["provider", "model", "product"],
)

BEDROCK_FALLBACK_TRIGGERED = Counter(
    "llm_gateway_bedrock_fallback_triggered_total",
    "Times Bedrock fallback was triggered after Anthropic failure",
    labelnames=["model", "product", "original_error_type"],
)

BEDROCK_FALLBACK_SUCCESS = Counter(
    "llm_gateway_bedrock_fallback_success_total",
    "Times Bedrock fallback succeeded",
    labelnames=["model", "product"],
)

BEDROCK_FALLBACK_FAILURE = Counter(
    "llm_gateway_bedrock_fallback_failure_total",
    "Times Bedrock fallback also failed",
    labelnames=["model", "product"],
)


def get_instrumentator() -> Instrumentator:
    return Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/_liveness", "/_readiness", "/metrics"],
        inprogress_labels=True,
    )
