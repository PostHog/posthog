from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

API_BASE_URL = "https://api.100ms.live"
ENDPOINTS = {
    "sessions": "sessions",
    "recordings": "recordings",
    "live_streams": "live-streams",
}
INCREMENTAL_FIELDS = {"sessions": [incremental_field("created_at")]}
PRIMARY_KEYS = ["id"]
PARTITION_KEY = "created_at"
# Sessions can run for 12 hours. Re-read recent sessions to include calls that have since ended.
SESSION_LOOKBACK_SECONDS = 24 * 60 * 60
AUTH_ERROR = "100ms authentication failed. Check the app access key and app secret in your 100ms dashboard."
PERMISSION_ERROR = "100ms denied access. Check that your credentials can read this workspace."
