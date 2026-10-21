from datetime import timedelta

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.gcore.com/cdn/"
PAGE_SIZE = 100
HISTORY_DAYS = 365

# Request logs are kept for three days and a request may span at most six hours.
LOGS_PAGE_SIZE = 1000
LOGS_HISTORY_DAYS = 2
LOGS_WINDOW = timedelta(hours=6)
LOGS_DELAY = timedelta(hours=1)

ENDPOINTS = {
    "resources": "resources",
    "origin_groups": "origin_groups",
    "ssl_certificates": "sslData",
    "cdn_requests": "statistics/series",
    "cdn_traffic": "statistics/series",
    "cdn_logs": "advanced/v1/logs",
    "cdn_daily_statistics": "statistics/aggregate/stats",
    "activity_logs": "activity_log/requests",
    "purge_statuses": "purge_statuses",
}
STATISTICS_METRICS = {"cdn_requests": "requests", "cdn_traffic": "sent_bytes"}
AGGREGATE_METRICS = (
    "requests",
    "sent_bytes",
    "upstream_bytes",
    "total_bytes",
    "responses_2xx",
    "responses_3xx",
    "responses_4xx",
    "responses_5xx",
    "responses_hit",
    "responses_miss",
    "cache_hit_traffic_ratio",
    "cache_hit_requests_ratio",
    "95_percentile",
    "max_bandwidth",
    "min_bandwidth",
)
WINDOWED_ENDPOINTS = {*STATISTICS_METRICS, "cdn_logs", "cdn_daily_statistics"}
PRIMARY_KEYS: dict[str, list[str] | None] = {
    **{name: ["id"] for name in ENDPOINTS},
    **{name: ["resource_id", "timestamp", "metric"] for name in STATISTICS_METRICS},
    "cdn_logs": None,
    "cdn_daily_statistics": ["resource_id", "region", "date"],
    "purge_statuses": ["purge_id"],
}
PARTITION_KEYS = {
    **{name: ["timestamp"] for name in STATISTICS_METRICS},
    "cdn_logs": ["timestamp"],
    "cdn_daily_statistics": ["date"],
}
INCREMENTAL_FIELDS = {
    "resources": [incremental_field("updated")],
    "cdn_requests": [incremental_field("timestamp")],
    "cdn_traffic": [incremental_field("timestamp")],
    "cdn_logs": [incremental_field("timestamp")],
    "cdn_daily_statistics": [incremental_field("date")],
    "activity_logs": [incremental_field("requested_at")],
    "purge_statuses": [incremental_field("created")],
}
INCREMENTAL_FILTER_PARAMS = {
    "resources": "min_updated",
    "activity_logs": "min_requested_at",
    "purge_statuses": "from_created",
}
APPEND_ONLY_ENDPOINTS = {"cdn_logs"}
MERGE_ONLY_ENDPOINTS = {*STATISTICS_METRICS, "cdn_daily_statistics"}
# Statistics are restated for recent days, and purges change status after they are created.
INCREMENTAL_LOOKBACK_SECONDS = {
    **dict.fromkeys(MERGE_ONLY_ENDPOINTS, 2 * 24 * 60 * 60),
    "purge_statuses": 24 * 60 * 60,
}
AUTH_ERRORS = {
    401: "Gcore rejected the API token. Check that the token is valid and has not expired.",
    403: "Gcore denied access. Check that the token has permission to read CDN data.",
}
