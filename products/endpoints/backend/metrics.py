from prometheus_client import Counter, Histogram


def query_kind_label(query: dict | None) -> str:
    if query and query.get("kind") == "HogQLQuery":
        return "hogql"
    return "insight"


ENDPOINT_EXECUTION_TOTAL = Counter(
    "posthog_endpoint_execution_total",
    "Endpoint executions that reached query execution (excludes concurrency rejections; see posthog_endpoint_concurrency_rejected_total)",
    labelnames=["execution_type", "query_kind", "status"],
)

ENDPOINT_EXECUTION_DURATION_SECONDS = Histogram(
    "posthog_endpoint_execution_duration_seconds",
    "End-to-end endpoint execution duration (excludes concurrency rejections)",
    labelnames=["execution_type", "query_kind"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 45, 90, 180, 300, float("inf")),
)

ENDPOINT_MATERIALIZATION_EVENT_TOTAL = Counter(
    "posthog_endpoint_materialization_event_total",
    "Materialization lifecycle events (enable/disable/deactivate_stale)",
    labelnames=["action", "status"],
)

ENDPOINT_DUCKLAKE_FALLBACK_TOTAL = Counter(
    "posthog_endpoint_ducklake_fallback_total",
    "DuckLake executions that fell back to inline",
)

ENDPOINT_RATE_LIMITED_TOTAL = Counter(
    "posthog_endpoint_rate_limited_total",
    "Rate-limited endpoint requests",
    labelnames=["scope"],
)

ENDPOINT_CONCURRENCY_REJECTED_TOTAL = Counter(
    "posthog_endpoint_concurrency_rejected_total",
    "Endpoint executions rejected because the concurrency limit was exceeded",
)

ENDPOINT_CACHE_RESULT_TOTAL = Counter(
    "posthog_endpoint_cache_result_total",
    "Endpoint responses by query-result cache outcome (hit or miss)",
    labelnames=["execution_type", "query_kind", "outcome"],
)

ENDPOINT_HOGQL_RESULT_ROWS = Histogram(
    "posthog_endpoint_hogql_result_rows",
    "Number of rows returned by a HogQL endpoint response",
    labelnames=["execution_type"],
    buckets=(10, 100, 1_000, 10_000, 100_000, 1_000_000, float("inf")),
)

ENDPOINT_VALIDATION_ERROR_TOTAL = Counter(
    "posthog_endpoint_validation_error_total",
    "Endpoint requests rejected at validation time, by reason",
    labelnames=["reason"],
)

ENDPOINT_MATERIALIZED_AGE_SECONDS = Histogram(
    "posthog_endpoint_materialized_age_seconds",
    "Age of the materialized data served, observed when a materialized table is used",
    buckets=(60, 300, 1800, 3600, 21600, 43200, 86400, 172800, 259200, 604800, 2592000, float("inf")),
)
