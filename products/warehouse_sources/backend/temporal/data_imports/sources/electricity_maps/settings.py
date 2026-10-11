from typing import Any

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.electricitymaps.com/v3"

CARBON_INTENSITY = "carbon_intensity"
POWER_BREAKDOWN = "power_breakdown"

ENDPOINTS = (CARBON_INTENSITY, POWER_BREAKDOWN)

API_VERSION_V3 = "v3"
API_VERSION_V4 = "v4"

# carbon_intensity's wire is unchanged between pins, so both versions request the same v3 path.
# power_breakdown's v3 path ("power-breakdown") is superseded by the v4 host's "electricity-mix"
# endpoint; the table name stays "power_breakdown" across both versions so existing schemas and
# syncs keep their identity across the pin change. The v4 entry is an absolute URL because
# resolve_request_url() returns an absolute http(s) path untouched, bypassing BASE_URL, so this one
# (endpoint, version) combination can move while carbon_intensity, and power_breakdown under a v3
# pin, keep posting to BASE_URL unchanged.
ENDPOINT_PATHS: dict[str, dict[str, str]] = {
    CARBON_INTENSITY: {
        API_VERSION_V3: "/carbon-intensity/past-range",
        API_VERSION_V4: "/carbon-intensity/past-range",
    },
    POWER_BREAKDOWN: {
        API_VERSION_V3: "/power-breakdown/past-range",
        API_VERSION_V4: "https://api.electricitymaps.com/v4/electricity-mix/past-range",
    },
}

_DATETIME_COLUMNS_WITH_CREATED_AT: dict[str, dict[str, Any]] = {
    "datetime": {"data_type": "timestamp"},
    "updatedAt": {"data_type": "timestamp"},
    "createdAt": {"data_type": "timestamp"},
}

# electricity-mix (power_breakdown's v4 wire) doesn't return createdAt.
_DATETIME_COLUMNS_NO_CREATED_AT: dict[str, dict[str, Any]] = {
    "datetime": {"data_type": "timestamp"},
    "updatedAt": {"data_type": "timestamp"},
}

ENDPOINT_COLUMNS: dict[str, dict[str, dict[str, Any]]] = {
    CARBON_INTENSITY: {
        API_VERSION_V3: _DATETIME_COLUMNS_WITH_CREATED_AT,
        API_VERSION_V4: _DATETIME_COLUMNS_WITH_CREATED_AT,
    },
    POWER_BREAKDOWN: {
        API_VERSION_V3: _DATETIME_COLUMNS_WITH_CREATED_AT,
        API_VERSION_V4: _DATETIME_COLUMNS_NO_CREATED_AT,
    },
}

# The past-range endpoints have no pagination: one request returns every hourly point in the
# requested window, and the API rejects windows longer than 10 days. Walk the range in windows
# comfortably under that cap.
WINDOW_DAYS = 5

# (connect, read) timeout in seconds. Without it, a stalled response holds the import worker
# indefinitely — see `request_timeout` on `ClientConfig`.
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)

# How far back the first sync reaches when the user leaves the history field empty. History depth
# is gated by the customer's Electricity Maps plan, so this stays modest.
DEFAULT_HISTORY_DAYS = 30

_DATETIME_FIELD: IncrementalField = {
    "label": "datetime",
    "type": IncrementalFieldType.DateTime,
    "field": "datetime",
    "field_type": IncrementalFieldType.DateTime,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    CARBON_INTENSITY: [_DATETIME_FIELD],
    POWER_BREAKDOWN: [_DATETIME_FIELD],
}
