from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.electricitymaps.com/v3"

CARBON_INTENSITY = "carbon_intensity"
POWER_BREAKDOWN = "power_breakdown"

ENDPOINTS = (CARBON_INTENSITY, POWER_BREAKDOWN)

ENDPOINT_PATHS: dict[str, str] = {
    CARBON_INTENSITY: "/carbon-intensity/past-range",
    POWER_BREAKDOWN: "/power-breakdown/past-range",
}

# The past-range endpoints have no pagination: one request returns every hourly point in the
# requested window, and the API rejects windows longer than 10 days. Walk the range in windows
# comfortably under that cap.
WINDOW_DAYS = 5

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
