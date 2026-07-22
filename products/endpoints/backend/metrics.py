from prometheus_client import Counter, Histogram


def query_kind_label(query: dict | None) -> str:
    if query and query.get("kind") == "HogQLQuery":
        return "hogql"
    return "insight"


ENDPOINT_EXECUTION_TOTAL = Counter(
    "posthog_endpoint_execution_total",
    "Endpoint executions that reached query execution (excludes concurrency rejections; see posthog_endpoint_concurrency_rejected_total). "
    "status is success; user_error (invalid query/variables in the user's endpoint, returned as 4xx); "
    "query_performance (the query hit a ClickHouse cost guardrail — timeout/memory/size/estimated-too-slow — returned as 400); "
    "capacity (shared ClickHouse pool momentarily saturated, returned as 503); "
    'or error (unexpected system failure). Only error is a system fault — alert on status="error"',
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

ENDPOINT_CONCURRENCY_REJECTED_TOTAL = Counter(
    "posthog_endpoint_concurrency_rejected_total",
    "Endpoint executions rejected because the concurrency limit was exceeded",
    # team_id is safe cardinality here: only teams actually hitting concurrency limits appear
    labelnames=["team_id"],
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

ENDPOINT_MATERIALIZED_FRESHNESS_RATIO = Histogram(
    "posthog_endpoint_materialized_freshness_ratio",
    "Age of the served materialized data relative to its data_freshness_seconds target; >1.0 means behind SLA",
    buckets=(0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2, 5, 10, float("inf")),
)
