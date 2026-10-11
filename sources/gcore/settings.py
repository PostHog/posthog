from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.gcore.com/cdn/"
PAGE_SIZE = 100
HISTORY_DAYS = 365

ENDPOINTS = {
    "resources": "resources",
    "origin_groups": "origin_groups",
    "ssl_certificates": "sslData",
    "cdn_requests": "statistics/series",
    "cdn_traffic": "statistics/series",
}
STATISTICS_METRICS = {"cdn_requests": "requests", "cdn_traffic": "sent_bytes"}
PRIMARY_KEYS = {
    name: ["resource_id", "timestamp", "metric"] if name in STATISTICS_METRICS else ["id"] for name in ENDPOINTS
}
PARTITION_KEYS = {name: ["timestamp"] for name in STATISTICS_METRICS}
INCREMENTAL_FIELDS = {
    "resources": [incremental_field("updated")],
    "cdn_requests": [incremental_field("timestamp")],
    "cdn_traffic": [incremental_field("timestamp")],
}
AUTH_ERRORS = {
    401: "Gcore rejected the API token. Check that the token is valid and has not expired.",
    403: "Gcore denied access. Check that the token has permission to read CDN data.",
}
