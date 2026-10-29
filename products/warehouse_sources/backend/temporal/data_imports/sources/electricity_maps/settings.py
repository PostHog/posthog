from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.electricitymaps.com/v3"

CARBON_INTENSITY = "carbon_intensity"
POWER_BREAKDOWN = "power_breakdown"
PRICE_DAY_AHEAD = "price_day_ahead"
LOCATIONAL_MARGINAL_PRICE_DAY_AHEAD = "locational_marginal_price_day_ahead"
CARBON_INTENSITY_FORECAST = "carbon_intensity_forecast"
ZONES = "zones"

ENDPOINTS = (
    CARBON_INTENSITY,
    POWER_BREAKDOWN,
    PRICE_DAY_AHEAD,
    LOCATIONAL_MARGINAL_PRICE_DAY_AHEAD,
    CARBON_INTENSITY_FORECAST,
    ZONES,
)

RANGE_ENDPOINT_PATHS: dict[str, str] = {
    CARBON_INTENSITY: "/carbon-intensity/past-range",
    POWER_BREAKDOWN: "/power-breakdown/past-range",
    PRICE_DAY_AHEAD: "/price-day-ahead/past-range",
    LOCATIONAL_MARGINAL_PRICE_DAY_AHEAD: "/locational-marginal-price-day-ahead/past-range",
}

# Locational marginal prices are published per United States pricing node rather than per zone,
# and their rows name the node in `entityName` instead of carrying a `zone`.
NODE_ENDPOINTS = frozenset({LOCATIONAL_MARGINAL_PRICE_DAY_AHEAD})

CARBON_INTENSITY_FORECAST_PATH = "/carbon-intensity/forecast"
ZONES_PATH = "/zones"

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
    PRICE_DAY_AHEAD: [_DATETIME_FIELD],
    LOCATIONAL_MARGINAL_PRICE_DAY_AHEAD: [_DATETIME_FIELD],
}
