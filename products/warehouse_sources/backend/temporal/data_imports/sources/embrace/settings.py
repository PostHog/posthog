from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

API_DOCS_URL = "https://embrace.io/docs/metrics-forwarding/metrics-api/"
REGION_HOSTS = {
    "default": "api.embrace.io",
    "us": "api-us1.embrace.io",
    "eu": "api-eu1.embrace.io",
}
ENDPOINTS = {
    "sessions": "hourly_sessions_total",
    "crashes": "hourly_crashes_total",
    "network_4xx": "hourly_network4xx_total",
    "network_5xx": "hourly_network5xx_total",
}
INCREMENTAL_FIELDS = {name: [incremental_field("timestamp")] for name in ENDPOINTS}
PRIMARY_KEYS = ["series_id", "timestamp"]
STEP_SECONDS = 3600
WINDOW_SECONDS = 24 * STEP_SECONDS
MAX_SYNC_SECONDS = 30 * WINDOW_SECONDS
AUTH_ERRORS = {
    401: "Embrace rejected the API token. Get a new Metrics API token from Settings > Organization > API.",
    403: "Embrace denied access. Check your Metrics API token, app ID, and region.",
}
