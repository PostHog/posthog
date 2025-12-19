from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

REQUEST_COUNT = Counter(
    "llm_gateway_requests_total",
    "Total LLM Gateway requests",
    labelnames=["endpoint", "provider", "model", "status_code", "auth_method"],
)

REQUEST_LATENCY = Histogram(
    "llm_gateway_request_duration_seconds",
    "Request latency",
    labelnames=["endpoint", "provider", "streaming"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

TOKENS_INPUT = Counter(
    "llm_gateway_tokens_input_total",
    "Total input tokens",
    labelnames=["provider", "model"],
)

TOKENS_OUTPUT = Counter(
    "llm_gateway_tokens_output_total",
    "Total output tokens",
    labelnames=["provider", "model"],
)

RATE_LIMIT_EXCEEDED = Counter(
    "llm_gateway_rate_limit_exceeded_total",
    "Rate limit exceeded events",
    labelnames=["scope"],
)

PROVIDER_ERRORS = Counter(
    "llm_gateway_provider_errors_total",
    "Provider API errors",
    labelnames=["provider", "error_type"],
)

ACTIVE_STREAMS = Gauge(
    "llm_gateway_active_streams",
    "Currently active streaming connections",
    labelnames=["provider"],
)

DB_POOL_SIZE = Gauge(
    "llm_gateway_db_pool_size",
    "Database connection pool size",
    labelnames=["state"],
)

PROVIDER_LATENCY = Histogram(
    "llm_gateway_provider_latency_seconds",
    "Latency to LLM provider API (excludes streaming time)",
    labelnames=["provider", "model"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)


def get_instrumentator() -> Instrumentator:
    return Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/_liveness", "/_readiness", "/metrics"],
        inprogress_labels=True,
    )
