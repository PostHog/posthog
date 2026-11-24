from products.warehouse_sources.sources.sdk import incremental_field

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
    "daily_users": "daily_users_total",
    "crash_free_users": "hourly_crashed_free_users",
    "exceptions": "hourly_exception_total",
    "web_vitals": "hourly_web_vital_total",
    "web_vital_p75": "hourly_web_vital_p75",
}
INCREMENTAL_FIELDS = {name: [incremental_field("timestamp")] for name in ENDPOINTS}
PRIMARY_KEYS = ["series_id", "timestamp"]
HOUR_SECONDS = 3600
DAY_SECONDS = 24 * HOUR_SECONDS
STEP_SECONDS = {
    name: DAY_SECONDS if metric.startswith("daily_") else HOUR_SECONDS for name, metric in ENDPOINTS.items()
}
WINDOW_POINTS = 24
MAX_SYNC_SECONDS = 30 * DAY_SECONDS
AUTH_ERRORS = {
    401: "Embrace rejected the API token. Get a new Metrics API token from Settings > Organization > API.",
    403: "Embrace denied access. Check your Metrics API token, app ID, and region.",
}
